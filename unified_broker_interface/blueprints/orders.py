"""
`/api/orders`: today's orders and trades across every broker, and placing, modifying and cancelling an order.

| Route | Does |
| --- | --- |
| `GET /details` | Every broker's orders, from `unified:orders:orders`, kept by `bin/unified/orders/api_order_details` every half second |
| `GET /trades` | Every broker's trades, from `unified:orders:trades`, kept by `bin/unified/orders/api_trade_details` every half second |
| `POST /place` | Places one order at the first broker the configured selector ranks that can take it, reading only Redis before the broker's place-order call |
| `PUT /modify` | Changes one open order at the broker whose order book in Redis holds its order id |
| `DELETE /cancel` | Cancels one order at the broker whose order book in Redis holds its order id |

`GET /details` and `GET /trades` ask no broker. `POST /place`, `PUT /modify` and `DELETE /cancel` each send exactly one request to one broker and never read MongoDB or PostgreSQL, so that the API's own work adds as little as possible to the time the broker takes.

Every Redis read the three order routes make is in this module. What differs between brokers, building the request and reading the answer, is in `unified_broker_interface/utilities/broker_orders/`, whose classes are handed decoded dictionaries and read no store themselves.
"""

import datetime
import hmac
import json
import time

import redis
from flask import jsonify, request

from unified_broker_interface.blueprints.base import BaseBlueprint
from unified_broker_interface.blueprints.base import authenticated
from unified_broker_interface.utilities.broker_orders.utilities.cancel_order_request import (
    CancelOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.connection_warmer import (
    ConnectionWarmer,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    UnmodifiableOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.registry import (
    BROKER_ORDER_CLASSES,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)
from unified_broker_interface.utilities.broker_selection.utilities.registry import (
    BROKER_SELECTOR_CLASSES,
)
from unified_broker_interface.utilities.instrument_cache import InstrumentCache
from unified_broker_interface.utilities.unified_documents import read_document
from utilities.configurations import api_configuration
from utilities.configurations import get_logger


class RefusedRequestError(Exception):
    """A request the order routes answer without calling a broker.

    Attributes:
        body (dict): The JSON body of the answer.
        status (int): The HTTP status of the answer.
    """

    def __init__(self, body, status):
        """Builds the refusal.

        Args:
            body (dict): The JSON body of the answer.
            status (int): The HTTP status of the answer.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(body.get('error'))
        self.body = body
        self.status = status


class OrdersBlueprint(BaseBlueprint):
    """The `/api/orders` routes: order and trade books from Redis, and placing, modifying and cancelling orders.

    Attributes:
        broker_names (list): Every broker's name, in the order the brokers take turns.
        broker_orders (dict): Each broker's name to its order class instance, built once per worker.
        broker_selector (BrokerSelector): The algorithm that orders the brokers an order is offered to, named by `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR`.
        instrument_cache (InstrumentCache): This worker's copy of the catalogue data placements and modifications have read under the current warm.
        connection_warmers (list): One `ConnectionWarmer` per broker named in `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS`, each running on its own daemon thread.
        logger (logging.Logger): The logger for failures that do not change an answer.
    """

    name = 'orders'
    routes = [
        ('/details', 'details', ['GET']),
        ('/trades', 'trades', ['GET']),
        ('/place', 'place', ['POST']),
        ('/modify', 'modify', ['PUT']),
        ('/cancel', 'cancel', ['DELETE']),
    ]

    def __init__(self):
        """Builds the blueprint, one order class per broker with no broker connection open yet, and the configured broker selector.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the configured broker selector is not a known one, so a misspelt name stops the worker from starting rather than routing orders some other way.
        """
        super().__init__()
        self.logger = get_logger('rest_api.orders')
        self.broker_names = []
        self.broker_orders = {}
        for broker_order_class in BROKER_ORDER_CLASSES:
            broker_orders = broker_order_class()
            self.broker_names.append(broker_orders.BROKER_NAME)
            self.broker_orders[broker_orders.BROKER_NAME] = broker_orders
        selector_name = api_configuration['order_broker_selector']
        if selector_name not in BROKER_SELECTOR_CLASSES:
            known_names = ', '.join(BROKER_SELECTOR_CLASSES)
            raise ValueError(
                f'unknown order broker selector {selector_name!r}; known selectors are {known_names}'
            )
        self.broker_selector = BROKER_SELECTOR_CLASSES[selector_name]()
        self.instrument_cache = InstrumentCache()
        self.connection_warmers = []
        self.start_connection_warmers()

    def start_connection_warmers(self):
        """Starts a connection warmer for each broker named in `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS`.

        Warming only saves time, so nothing about it may stop the API: an unknown broker name is logged and ignored, and any other failure is logged and leaves warming off. A broker without a `WARM_URL`, such as Kotak, is pinged only once a request has named its host.

        Returns:
            None: This method returns nothing.
        """
        try:
            for broker_name in api_configuration['order_warm_brokers']:
                if not broker_name:
                    continue
                broker_orders = self.broker_orders.get(broker_name)
                if broker_orders is None:
                    self.logger.warning(
                        'not warming order connections to %r, which is not a broker',
                        broker_name,
                    )
                    continue
                warmer = ConnectionWarmer(broker_orders, self.logger)
                warmer.start()
                self.connection_warmers.append(warmer)
        except Exception:
            self.logger.exception('order connection warming could not start')

    @authenticated
    def details(self):
        """Answers today's orders at every broker, with how each broker's data was read.

        See `utilities/unified_documents.py` for when the document is not served.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        body, status = read_document(
            self.cache,
            'unified:orders:orders',
            30,
            'orders',
        )
        return jsonify(body), status

    @authenticated
    def trades(self):
        """Answers today's trades at every broker, with how each broker's data was read.

        See `utilities/unified_documents.py` for when the document is not served.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        body, status = read_document(
            self.cache,
            'unified:orders:trades',
            30,
            'trades',
        )
        return jsonify(body), status

    def refuse(self, message, status, **fields):
        """Builds the refusal for a request answered without calling a broker.

        Args:
            message (str): The error message.
            status (int): The HTTP status.
            **fields (object): Other fields for the answer's body, such as `broker` or `skipped`.

        Returns:
            RefusedRequestError: The refusal, for the caller to raise.
        """
        body = {
            'error': message,
        }
        body.update(fields)
        return RefusedRequestError(body, status)

    def check_access_token(self, access_token, token_document_text):
        """Checks the request's access token against the API's token document from Redis.

        Args:
            access_token (str): The `access-token` header.
            token_document_text (str | None): The API's token document as Redis holds it.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 401 when the token is wrong or has expired.
        """
        token_document = None
        if token_document_text:
            try:
                token_document = json.loads(token_document_text)
            except ValueError:
                token_document = None
        stored_token = None
        if isinstance(token_document, dict):
            stored_token = token_document.get('access_token')
        if not stored_token or not hmac.compare_digest(
            access_token.encode(),
            str(stored_token).encode(),
        ):
            raise self.refuse('Invalid access token', 401)
        try:
            expires_at = datetime.datetime.strptime(
                token_document['expires_at'],
                '%Y-%m-%d %H:%M:%S.%f',
            )
        except (KeyError, TypeError, ValueError):
            expires_at = None
        if expires_at is None or expires_at <= datetime.datetime.now():
            raise self.refuse('Access token has expired', 401)

    def decode_login(self, login_text):
        """Decodes a broker's login from Redis.

        Args:
            login_text (str | None): The login as Redis holds it.

        Returns:
            object: The decoded login, or None when there is none or it is not JSON.
        """
        if not login_text:
            return None
        try:
            return json.loads(login_text)
        except ValueError:
            return None

    def decode_settings(self, settings_text):
        """Decodes a broker's settings from Redis.

        Args:
            settings_text (str | None): The settings as Redis holds them.

        Returns:
            dict: The decoded settings, or an empty dictionary when there are none or they are not a JSON object.
        """
        if not settings_text:
            return {}
        try:
            settings = json.loads(settings_text)
        except ValueError:
            return {}
        if not isinstance(settings, dict):
            return {}
        return settings

    def redis_unreadable(self, error):
        """Builds the refusal for a Redis read that failed.

        Args:
            error (redis.RedisError): The failure.

        Returns:
            RefusedRequestError: The refusal with HTTP 503, for the caller to raise.
        """
        return self.refuse(f'Redis could not be read: {error}', 503)

    def place(self):
        """Places one order at the first broker the configured broker selector ranks that can take it.

        The JSON body names the instrument by `instrument_id`, or by `exchange`, `segment` and the segment's identity fields (`symbol`, or `underlying_symbol` and `expiry_date`, and for an option `strike_price` and `option_type`).
        It gives `transaction_type` (BUY or SELL), `product` (CNC, MIS or NRML), `order_type` (MARKET, LIMIT, SL or SL-M) and `quantity` in units.
        It may give `validity` (DAY or IOC, default DAY), `price`, `trigger_price`, `disclosed_quantity`, `after_market`, `tag` and `dry_run`.

        The method reads Redis in one to three round trips and then sends one request to one broker: one for the token, logins, settings and mapping marker, one for the instrument's catalogue data unless this worker already holds it under the current warm, and one more to find an instrument named by its fields unless that lookup is held too.
        It never reads MongoDB or PostgreSQL, never calls a broker for anything but the order itself, and never retries a sent order at another broker.
        With `dry_run` it answers with the request it would have sent instead of sending it.
        Every failure is answered with an HTTP status rather than raised.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int), which is 200 when the broker accepted the order or for a dry run, 422 when the broker refused it, 504 when the outcome is unknown, 400 for an order that is not valid, 401 for a missing, wrong or expired access token, 404 for an instrument that is not mapped, and 503 when Redis cannot be read or no broker can take the order.
        """
        started_at = time.perf_counter()
        try:
            return self.place_order(started_at)
        except RefusedRequestError as refusal:
            return jsonify(refusal.body), refusal.status

    def place_order(self, started_at):
        """Does the work of `place`, raising a refusal for any request answered without calling a broker.

        Args:
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a request answered without calling a broker.
        """
        access_token = request.headers.get('access-token')
        if not access_token:
            raise self.refuse('Access token is required', 401)

        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', 'unified_broker_interface')
            pipeline.get('unified:catalogue:current_date')
            pipeline.hmget('last_login', self.broker_names)
            pipeline.hmget('settings', self.broker_names)
            pipeline.get('unified:catalogue:warm_identifier')
            first_replies = pipeline.execute()
        except redis.RedisError as error:
            raise self.redis_unreadable(error)
        token_document_text = first_replies[0]
        mapping_date_text = first_replies[1]
        login_texts = first_replies[2]
        settings_texts = first_replies[3]
        warm_identifier = first_replies[4]

        self.check_access_token(access_token, token_document_text)

        try:
            order = PlaceOrderRequest(request.get_json(silent=True))
        except InvalidOrderError as error:
            raise self.refuse(str(error), 400)

        rotation = self.rotation()
        if not mapping_date_text:
            raise self.refuse('no instruments have been mapped yet', 503)
        catalogue_key_prefix = f'unified:catalogue:{mapping_date_text}:'

        instrument_id = order.instrument_id
        if instrument_id is None:
            instrument_id = self.instrument_cache.instrument_lookup(
                mapping_date_text,
                warm_identifier,
                order.catalogue_segment,
                order.catalogue_prefix,
            )
        if instrument_id is None:
            instrument_id = self.find_instrument_id(order, catalogue_key_prefix)
            self.instrument_cache.keep_instrument_lookup(
                mapping_date_text,
                warm_identifier,
                order.catalogue_segment,
                order.catalogue_prefix,
                instrument_id,
            )

        kept_texts = self.instrument_cache.instrument(
            mapping_date_text,
            warm_identifier,
            instrument_id,
        )
        pipeline = self.cache.pipeline(transaction=False)
        if kept_texts is None:
            pipeline.hget(catalogue_key_prefix + 'identity', instrument_id)
            pipeline.hget(catalogue_key_prefix + 'order_handles', instrument_id)
            pipeline.hget(catalogue_key_prefix + 'contract_sizes', instrument_id)
        selector_command_count = self.broker_selector.queue_redis_commands(
            pipeline,
            order,
            instrument_id,
        )
        second_replies = []
        if kept_texts is None or selector_command_count > 0:
            try:
                second_replies = pipeline.execute()
            except redis.RedisError as error:
                raise self.redis_unreadable(error)
        if kept_texts is None:
            identity_text = second_replies[0]
            handles_text = second_replies[1]
            contract_size_text = second_replies[2]
            selector_replies = second_replies[3:]
        else:
            identity_text = kept_texts[0]
            handles_text = kept_texts[1]
            contract_size_text = kept_texts[2]
            selector_replies = second_replies

        instrument = self.decode_instrument(
            instrument_id,
            identity_text,
            handles_text,
            contract_size_text,
        )
        if kept_texts is None:
            self.instrument_cache.keep_instrument(
                mapping_date_text,
                warm_identifier,
                instrument_id,
                identity_text,
                handles_text,
                contract_size_text,
            )
        if not instrument.is_tradeable():
            message = f'orders are not sent for {instrument.segment} instruments'
            raise self.refuse(message, 400)
        self.check_contract_size(order, instrument)

        ranked_brokers = self.broker_selector.ranked_brokers(
            order,
            instrument,
            rotation,
            selector_replies,
        )
        broker_orders, skipped = self.choose_broker(
            order,
            instrument,
            rotation,
            ranked_brokers,
            login_texts,
            settings_texts,
        )
        broker_name = broker_orders.BROKER_NAME
        position = self.broker_names.index(broker_name)
        handle = instrument.handles.get(broker_name)
        login = self.decode_login(login_texts[position])
        settings = self.decode_settings(settings_texts[position])

        size_problem = None
        if instrument.is_securities_market():
            size_problem = order.lot_size_problem(handle)
        if size_problem is None:
            size_problem = order.tick_size_problem(instrument.handles)
        if size_problem is not None:
            raise self.refuse(size_problem, 400)

        quantity, disclosed_quantity = broker_orders.order_quantities(
            order,
            instrument,
            handle,
        )
        broker_order = order.with_quantities(quantity, disclosed_quantity)
        broker_request = broker_orders.build_place_request(
            broker_order,
            instrument,
            handle,
            login,
            settings,
        )

        if order.dry_run:
            preparation_milliseconds = (time.perf_counter() - started_at) * 1000
            return jsonify({
                'broker': broker_name,
                'instrument_id': instrument_id,
                'tag': broker_request.tag,
                'dry_run': True,
                'request': broker_request.shown(),
                'skipped': skipped,
                'timing_ms': {
                    'preparation': round(preparation_milliseconds, 3),
                },
            }), 200

        answer = broker_orders.send_place(broker_request)
        self.record_outcome(broker_name, answer)
        preparation_milliseconds = (answer.sent_at - started_at) * 1000
        return jsonify({
            'broker': broker_name,
            'instrument_id': instrument_id,
            'tag': broker_request.tag,
            'outcome': answer.outcome,
            'order_id': answer.order_id,
            'status_message': answer.status_message,
            'broker_response': answer.response_body,
            'skipped': skipped,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': answer.broker_milliseconds(),
            },
        }), answer.http_status()

    def rotation(self):
        """Lists the brokers that take turns, which is every broker not excluded by configuration.

        Returns:
            list: The broker names, in turn order.

        Raises:
            RefusedRequestError: With HTTP 503 when every broker is excluded.
        """
        excluded_brokers = api_configuration['order_excluded_brokers']
        rotation = []
        for broker_name in self.broker_names:
            if broker_name not in excluded_brokers:
                rotation.append(broker_name)
        if not rotation:
            message = 'every broker is excluded from order placement'
            raise self.refuse(message, 503)
        return rotation

    def find_instrument_id(self, order, catalogue_key_prefix):
        """Finds the instrument an order names by identity fields, in the segment's catalogue.

        Args:
            order (PlaceOrderRequest): The validated order, with `catalogue_segment` and `catalogue_prefix` set.
            catalogue_key_prefix (str): The prefix of today's catalogue keys.

        Returns:
            str: The instrument id.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read, 404 when no instrument matches, and 400 when more than one does.
        """
        catalogue_key = (
            catalogue_key_prefix + 'catalogue:' + order.catalogue_segment
        )
        prefix_bytes = order.catalogue_prefix.encode()
        try:
            members = self.cache.zrangebylex(
                catalogue_key,
                b'[' + prefix_bytes,
                b'(' + prefix_bytes + b'\xff',
                start=0,
                num=2,
            )
        except redis.RedisError as error:
            raise self.redis_unreadable(error)
        if not members:
            raise self.refuse('the instrument is not mapped', 404)
        if len(members) > 1:
            message = (
                'the identity fields match more than one instrument, so give instrument_id'
            )
            raise self.refuse(message, 400)
        return str(members[0]).rsplit('|', 1)[1]

    def decode_instrument(
        self,
        instrument_id,
        identity_text,
        handles_text,
        contract_size_text,
    ):
        """Decodes the instrument from its identity, order handles and contract size decision in Redis.

        A contract size decision that is missing or not a JSON object is decoded as None, which leaves a currency or commodity derivative untradeable rather than refusing an order on any other instrument.

        Args:
            instrument_id (str): The instrument id.
            identity_text (str | None): The identity as Redis holds it.
            handles_text (str | None): The order handles as Redis holds them.
            contract_size_text (str | None): The contract size decision as Redis holds it.

        Returns:
            Instrument: The instrument, which may not be tradeable.

        Raises:
            RefusedRequestError: With HTTP 404 when either is missing or not a JSON object.
        """
        identity = None
        handles = None
        try:
            if identity_text:
                identity = json.loads(identity_text)
            if handles_text:
                handles = json.loads(handles_text)
        except ValueError:
            identity = None
            handles = None
        if not isinstance(identity, dict) or not isinstance(handles, dict):
            raise self.refuse('the instrument is not mapped', 404)
        contract_size = None
        if contract_size_text:
            try:
                contract_size = json.loads(contract_size_text)
            except ValueError:
                contract_size = None
        if not isinstance(contract_size, dict):
            contract_size = None
        return Instrument(instrument_id, identity, handles, contract_size)

    def check_contract_size(self, order, instrument):
        """Checks a currency or commodity order against the contract size decided this morning.

        Such a contract's lot size is taken only from `unified.contract_sizes`, as the warm copies it to Redis, because the brokers' own lot sizes count lots in different units. An order on a contract whose size is not trusted today is refused.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 503 when the contract's size is not trusted today, and 400 when a quantity is not a whole number of lots.
        """
        if instrument.is_securities_market():
            return
        units_per_lot = instrument.trusted_units_per_lot()
        if units_per_lot is None:
            status = instrument.contract_size_status()
            raise self.refuse(
                f'the contract size of this {instrument.segment} instrument is not trusted today ({status}), so no order is sent',
                503,
                instrument_id=instrument.instrument_id,
                contract_size_status=status,
            )
        problem = order.contract_lot_problem(units_per_lot)
        if problem is not None:
            raise self.refuse(problem, 400)

    def record_outcome(self, broker_name, answer):
        """Hands a sent order's answer to the broker selector, so a selector's failure cannot change the answer to an order already sent.

        Args:
            broker_name (str): The broker the order was sent to.
            answer (BrokerAnswer): The broker's answer.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.broker_selector.record_outcome(broker_name, answer)
        except Exception:
            self.logger.exception(
                'broker selector %s failed to record an outcome from %s',
                self.broker_selector.NAME,
                broker_name,
            )

    def choose_broker(
        self,
        order,
        instrument,
        rotation,
        ranked_brokers,
        login_texts,
        settings_texts,
    ):
        """Offers the order to the brokers in the selector's order, passing over every broker that cannot take it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            rotation (list): The broker names not excluded by configuration.
            ranked_brokers (list): The broker names in the order the selector ranked them; a name not in `rotation` is ignored.
            login_texts (list): Every broker's login as Redis holds it, in `broker_names` order.
            settings_texts (list): Every broker's settings as Redis holds them, in `broker_names` order.

        Returns:
            tuple: `(broker_orders, skipped)`, where `broker_orders` is the chosen broker's order class instance and `skipped` lists each broker passed over as a dictionary with `broker` and `reason`.

        Raises:
            RefusedRequestError: With HTTP 503 when no broker can take the order.
        """
        skipped = []
        offered = []
        for broker_name in ranked_brokers:
            if broker_name not in rotation or broker_name in offered:
                continue
            offered.append(broker_name)
            position = self.broker_names.index(broker_name)
            broker_orders = self.broker_orders[broker_name]
            reason = broker_orders.place_skip_reason(
                order,
                instrument,
                instrument.handles.get(broker_name),
                self.decode_login(login_texts[position]),
                self.decode_settings(settings_texts[position]),
            )
            if reason is None:
                return broker_orders, skipped
            skipped.append({
                'broker': broker_name,
                'reason': reason,
            })
        raise self.refuse(
            'no broker can take this order',
            503,
            instrument_id=instrument.instrument_id,
            skipped=skipped,
        )

    def modify(self):
        """Changes one open order at the broker whose order book holds it.

        The JSON body names the order by `order_id`, the broker's own order id as `POST /place` and `GET /details` answer it, and may give `broker`, needed only when two brokers hold an order with the same id, and `dry_run`; these three may also come from the query string.
        The body gives at least one of `quantity` (the new total quantity, in units as `POST /place` takes it), `disclosed_quantity`, `price`, `trigger_price`, `order_type` and `validity`, and every field it leaves out keeps the stored order's value.

        The broker is found as `cancel` finds it, in the `<broker>:orders:orders` hashes the broker's order scripts keep.
        The instrument is found from the stored order's broker token in today's catalogue, so that a changed quantity can be checked against the lot size and converted into the broker's terms and a changed price checked against the tick size, as `POST /place` checks them.
        The method reads Redis in one to three round trips and then sends one request to one broker: one for the token, logins, settings, mapping marker and order books, one for the instruments the broker's token names unless this worker holds them, and one for those instruments' catalogue data unless this worker holds it.
        It never reads MongoDB or PostgreSQL, ignores excluded brokers, and never retries a sent modification.
        With `dry_run` it answers with the request it would have sent instead of sending it.
        Every failure is answered with an HTTP status rather than raised.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int), which is 200 when the broker accepted the modification or for a dry run, 422 when the broker refused it, 504 when the outcome is unknown, 400 for an invalid body, a field the broker cannot change, a quantity that is not a whole number of lots or a price that is not a whole number of ticks, 401 for a missing, wrong or expired access token, 404 when no broker's order book in Redis holds the order, 409 when the order has already finished, two brokers hold the order id, or the stored order is one the route does not change, 501 when the broker's modify request is not built, and 503 when Redis cannot be read or does not hold what the modification needs, or a changed quantity cannot be converted.
        """
        started_at = time.perf_counter()
        try:
            return self.modify_order(started_at)
        except RefusedRequestError as refusal:
            return jsonify(refusal.body), refusal.status

    def modify_order(self, started_at):
        """Does the work of `modify`, raising a refusal for any request answered without calling a broker.

        Args:
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a request answered without calling a broker.
        """
        access_token = request.headers.get('access-token')
        if not access_token:
            raise self.refuse('Access token is required', 401)

        try:
            modify_request = ModifyOrderRequest(
                request.get_json(silent=True),
                request.args,
                self.broker_names,
            )
        except InvalidOrderError as error:
            raise self.refuse(str(error), 400)
        order_id = modify_request.order_id

        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', 'unified_broker_interface')
            pipeline.get('unified:catalogue:current_date')
            pipeline.get('unified:catalogue:warm_identifier')
            pipeline.hmget('last_login', self.broker_names)
            pipeline.hmget('settings', self.broker_names)
            for broker_name in self.broker_names:
                pipeline.hget(f'{broker_name}:orders:orders', order_id)
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise self.redis_unreadable(error)
        token_document_text = replies[0]
        mapping_date_text = replies[1]
        warm_identifier = replies[2]
        login_texts = replies[3]
        settings_texts = replies[4]
        order_texts = replies[5:]

        self.check_access_token(access_token, token_document_text)

        broker_name, stored_order = self.find_stored_order(
            modify_request,
            order_texts,
        )
        if stored_order.is_finished():
            raise self.refuse(
                f'the order is already {stored_order.status}',
                409,
                broker=broker_name,
                order_id=order_id,
            )

        broker_orders = self.broker_orders[broker_name]
        if not broker_orders.takes_modifications():
            raise self.refuse(
                f'modifying orders is not implemented for {broker_name}',
                501,
                broker=broker_name,
                order_id=order_id,
            )
        position = self.broker_names.index(broker_name)
        login = self.decode_login(login_texts[position])
        settings = self.decode_settings(settings_texts[position])
        problem = broker_orders.modify_problem(login, settings)
        if problem is not None:
            raise self.refuse(
                problem,
                503,
                broker=broker_name,
                order_id=order_id,
            )
        problem = broker_orders.modify_field_problem(modify_request)
        if problem is not None:
            raise self.refuse(
                problem,
                400,
                broker=broker_name,
                order_id=order_id,
            )

        try:
            modification = OrderModification(modify_request, stored_order)
        except InvalidOrderError as error:
            raise self.refuse(
                str(error),
                400,
                broker=broker_name,
                order_id=order_id,
            )
        except UnmodifiableOrderError as error:
            raise self.refuse(
                str(error),
                409,
                broker=broker_name,
                order_id=order_id,
            )
        except OrderNotReadyError as error:
            raise self.refuse(
                str(error),
                503,
                broker=broker_name,
                order_id=order_id,
            )

        instrument = self.resolve_order_instrument(
            broker_orders,
            modification,
            mapping_date_text,
            warm_identifier,
        )
        instrument_id = None
        if instrument is not None:
            instrument_id = instrument.instrument_id

        if modification.changes('quantity') or modification.changes(
            'disclosed_quantity',
        ):
            modification = self.convert_modified_quantities(
                broker_orders,
                modify_request,
                modification,
                instrument,
            )

        if instrument is not None:
            changed_prices = {}
            if modification.changes('price'):
                changed_prices['price'] = modify_request.price
            if modification.changes('trigger_price'):
                changed_prices['trigger_price'] = modify_request.trigger_price
            problem = modify_request.prices_off_tick_problem(
                instrument.handles,
                changed_prices,
            )
            if problem is not None:
                raise self.refuse(
                    problem,
                    400,
                    broker=broker_name,
                    order_id=order_id,
                )

        try:
            broker_request = broker_orders.build_modify_request(
                order_id,
                stored_order,
                modification,
                login,
                settings,
            )
        except OrderNotReadyError as error:
            raise self.refuse(
                str(error),
                503,
                broker=broker_name,
                order_id=order_id,
            )

        if modify_request.dry_run:
            preparation_milliseconds = (time.perf_counter() - started_at) * 1000
            return jsonify({
                'broker': broker_name,
                'order_id': order_id,
                'instrument_id': instrument_id,
                'status_before_modify': stored_order.status,
                'dry_run': True,
                'request': broker_request.shown(),
                'timing_ms': {
                    'preparation': round(preparation_milliseconds, 3),
                },
            }), 200

        answer = broker_orders.send_modify(broker_request)
        preparation_milliseconds = (answer.sent_at - started_at) * 1000
        return jsonify({
            'broker': broker_name,
            'order_id': order_id,
            'instrument_id': instrument_id,
            'status_before_modify': stored_order.status,
            'outcome': answer.outcome,
            'status_message': answer.status_message,
            'broker_response': answer.response_body,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': answer.broker_milliseconds(),
            },
        }), answer.http_status()

    def resolve_order_instrument(
        self,
        broker_orders,
        modification,
        mapping_date_text,
        warm_identifier,
    ):
        """Finds the one instrument in today's catalogue that a stored order's broker token and exchange name.

        The candidates are the instruments `unified:catalogue:<date>:tokens:<broker>` lists for the token. One is kept only when it is tradeable, its market is one the broker takes, the broker's order handle for it carries the same token, and its market fits the stored exchange code. The instrument is found only when exactly one candidate is kept, because several brokers number tokens per exchange, so one token can name instruments on NSE and BSE.

        Args:
            broker_orders (BrokerOrders): The order class of the broker holding the order.
            modification (OrderModification): The order after the change, carrying the stored token and exchange.
            mapping_date_text (str | None): The mapping date Redis holds.
            warm_identifier (str | None): The warm identifier Redis holds.

        Returns:
            Instrument | None: The instrument, or None when there is no mapping, no stored token, or not exactly one candidate.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read.
        """
        broker_token = modification.instrument_token
        if not mapping_date_text or broker_token is None:
            return None
        broker_name = broker_orders.BROKER_NAME
        catalogue_key_prefix = f'unified:catalogue:{mapping_date_text}:'

        candidates_text = self.instrument_cache.token_candidates_text(
            mapping_date_text,
            warm_identifier,
            broker_name,
            broker_token,
        )
        if candidates_text is None:
            try:
                candidates_text = self.cache.hget(
                    catalogue_key_prefix + 'tokens:' + broker_name,
                    broker_token,
                )
            except redis.RedisError as error:
                raise self.redis_unreadable(error)
            if not candidates_text:
                return None
            self.instrument_cache.keep_token_candidates(
                mapping_date_text,
                warm_identifier,
                broker_name,
                broker_token,
                candidates_text,
            )

        candidate_ids = []
        for candidate_id in candidates_text.split(','):
            if candidate_id and candidate_id not in candidate_ids:
                candidate_ids.append(candidate_id)
        texts_by_id = {}
        unkept_ids = []
        for candidate_id in candidate_ids:
            kept_texts = self.instrument_cache.instrument(
                mapping_date_text,
                warm_identifier,
                candidate_id,
            )
            if kept_texts is None:
                unkept_ids.append(candidate_id)
            else:
                texts_by_id[candidate_id] = kept_texts
        if unkept_ids:
            try:
                pipeline = self.cache.pipeline(transaction=False)
                for candidate_id in unkept_ids:
                    pipeline.hget(
                        catalogue_key_prefix + 'identity',
                        candidate_id,
                    )
                    pipeline.hget(
                        catalogue_key_prefix + 'order_handles',
                        candidate_id,
                    )
                    pipeline.hget(
                        catalogue_key_prefix + 'contract_sizes',
                        candidate_id,
                    )
                replies = pipeline.execute()
            except redis.RedisError as error:
                raise self.redis_unreadable(error)
            for index, candidate_id in enumerate(unkept_ids):
                texts_by_id[candidate_id] = (
                    replies[3 * index],
                    replies[3 * index + 1],
                    replies[3 * index + 2],
                )

        matches = []
        for candidate_id in candidate_ids:
            texts = texts_by_id.get(candidate_id)
            if texts is None:
                continue
            try:
                instrument = self.decode_instrument(
                    candidate_id,
                    texts[0],
                    texts[1],
                    texts[2],
                )
            except RefusedRequestError:
                continue
            if candidate_id in unkept_ids:
                self.instrument_cache.keep_instrument(
                    mapping_date_text,
                    warm_identifier,
                    candidate_id,
                    texts[0],
                    texts[1],
                    texts[2],
                )
            if not instrument.is_tradeable():
                continue
            if instrument.market() not in broker_orders.MARKETS:
                continue
            handle = instrument.handles.get(broker_name)
            if not isinstance(handle, dict):
                continue
            if str(handle.get('broker_token')) != broker_token:
                continue
            if not broker_orders.stored_exchange_matches(
                instrument,
                modification.exchange,
            ):
                continue
            matches.append(instrument)
        if len(matches) != 1:
            return None
        return matches[0]

    def convert_modified_quantities(
        self,
        broker_orders,
        modify_request,
        modification,
        instrument,
    ):
        """Checks a changed quantity or disclosed quantity and converts it from units into the broker's own terms.

        A quantity the caller did not change keeps the stored value, which is already in the broker's terms. For a currency or commodity instrument today's contract size decision must be trusted, as `POST /place` requires; a price-only change does not reach this method, so it is not held back by an untrusted size.

        Args:
            broker_orders (BrokerOrders): The order class of the broker holding the order.
            modify_request (ModifyOrderRequest): The validated modification.
            modification (OrderModification): The order after the change.
            instrument (Instrument | None): The order's instrument, or None when it was not found.

        Returns:
            OrderModification: A copy carrying both quantities in the broker's own terms.

        Raises:
            RefusedRequestError: With HTTP 503 when the quantity cannot be converted or the contract size is not trusted today, and 400 when a quantity is not a whole number of lots or the disclosed quantity is more than the quantity.
        """
        broker_name = broker_orders.BROKER_NAME
        order_id = modify_request.order_id
        quantity = modification.quantity
        disclosed_quantity = modification.disclosed_quantity

        if instrument is None:
            if not broker_orders.takes_only_securities():
                raise self.refuse(
                    "the order's instrument could not be found in today's catalogue, so a changed quantity cannot be converted into the broker's terms",
                    503,
                    broker=broker_name,
                    order_id=order_id,
                )
            if modify_request.changes('quantity'):
                quantity = modify_request.quantity
            if modify_request.changes('disclosed_quantity'):
                disclosed_quantity = modify_request.disclosed_quantity
        else:
            handle = instrument.handles.get(broker_name)
            problem = broker_orders.quantity_conversion_problem(
                instrument,
                handle,
            )
            if problem is not None:
                raise self.refuse(
                    problem,
                    503,
                    broker=broker_name,
                    order_id=order_id,
                    instrument_id=instrument.instrument_id,
                )
            if instrument.is_securities_market():
                if modify_request.changes('quantity'):
                    problem = modify_request.handle_lot_size_problem(
                        modify_request.quantity,
                        handle,
                    )
            else:
                units_per_lot = instrument.trusted_units_per_lot()
                if units_per_lot is None:
                    status = instrument.contract_size_status()
                    raise self.refuse(
                        f'the contract size of this {instrument.segment} instrument is not trusted today ({status}), so its quantity cannot be changed',
                        503,
                        broker=broker_name,
                        order_id=order_id,
                        instrument_id=instrument.instrument_id,
                        contract_size_status=status,
                    )
                changed_quantities = {
                    'quantity': modify_request.quantity,
                    'disclosed_quantity': modify_request.disclosed_quantity,
                }
                problem = modify_request.quantities_off_lot_problem(
                    units_per_lot,
                    changed_quantities,
                )
            if problem is not None:
                raise self.refuse(
                    problem,
                    400,
                    broker=broker_name,
                    order_id=order_id,
                    instrument_id=instrument.instrument_id,
                )
            if modify_request.changes('quantity'):
                quantity = broker_orders.broker_quantity(
                    modify_request.quantity,
                    instrument,
                    handle,
                )
            if modify_request.changes('disclosed_quantity'):
                disclosed_quantity = broker_orders.broker_quantity(
                    modify_request.disclosed_quantity,
                    instrument,
                    handle,
                )

        if disclosed_quantity > quantity:
            raise self.refuse(
                'disclosed_quantity cannot be more than quantity',
                400,
                broker=broker_name,
                order_id=order_id,
            )
        return modification.with_quantities(quantity, disclosed_quantity)

    def cancel(self):
        """Cancels one order at the broker whose order book holds it.

        The order is named by `order_id`, the broker's own order id as `POST /place` and `GET /details` answer it, given in the JSON body or the query string.
        `broker` may also be given, and is needed only when two brokers hold an order with the same id.
        With `dry_run` it answers with the request it would have sent instead of sending it.

        The broker is found by looking the order id up in every broker's `<broker>:orders:orders` hash, which the broker's order poller and order update websocket keep in Redis.
        An order can therefore be cancelled only once one of those scripts has recorded it; a Stoxkart order is recorded by its order websocket or by its once-a-second poller.
        The method reads Redis in one round trip and then sends one request to one broker.
        It never reads MongoDB or PostgreSQL and never retries a sent cancel.
        Every failure is answered with an HTTP status rather than raised.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int), which is 200 when the broker accepted the cancel or for a dry run, 422 when the broker refused it, 504 when the outcome is unknown, 400 for a malformed order_id, broker or dry_run, 401 for a missing, wrong or expired access token, 404 when no broker's order book in Redis holds the order, 409 when the order has already finished or two brokers hold the order id, and 503 when Redis cannot be read or does not hold the broker's login, settings or the order's details.
        """
        started_at = time.perf_counter()
        try:
            return self.cancel_order(started_at)
        except RefusedRequestError as refusal:
            return jsonify(refusal.body), refusal.status

    def cancel_order(self, started_at):
        """Does the work of `cancel`, raising a refusal for any request answered without calling a broker.

        Args:
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a request answered without calling a broker.
        """
        access_token = request.headers.get('access-token')
        if not access_token:
            raise self.refuse('Access token is required', 401)

        try:
            cancel_request = CancelOrderRequest(
                request.get_json(silent=True),
                request.args,
                self.broker_names,
            )
        except InvalidOrderError as error:
            raise self.refuse(str(error), 400)
        order_id = cancel_request.order_id

        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', 'unified_broker_interface')
            pipeline.hmget('last_login', self.broker_names)
            pipeline.hmget('settings', self.broker_names)
            for broker_name in self.broker_names:
                pipeline.hget(f'{broker_name}:orders:orders', order_id)
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise self.redis_unreadable(error)
        token_document_text = replies[0]
        login_texts = replies[1]
        settings_texts = replies[2]
        order_texts = replies[3:]

        self.check_access_token(access_token, token_document_text)

        broker_name, stored_order = self.find_stored_order(
            cancel_request,
            order_texts,
        )
        if stored_order.is_finished():
            raise self.refuse(
                f'the order is already {stored_order.status}',
                409,
                broker=broker_name,
                order_id=order_id,
            )

        broker_orders = self.broker_orders[broker_name]
        position = self.broker_names.index(broker_name)
        login = self.decode_login(login_texts[position])
        settings = self.decode_settings(settings_texts[position])
        problem = broker_orders.cancel_problem(login, settings)
        if problem is not None:
            raise self.refuse(
                problem,
                503,
                broker=broker_name,
                order_id=order_id,
            )
        try:
            broker_request = broker_orders.build_cancel_request(
                order_id,
                stored_order,
                login,
                settings,
            )
        except OrderNotReadyError as error:
            raise self.refuse(
                str(error),
                503,
                broker=broker_name,
                order_id=order_id,
            )

        if cancel_request.dry_run:
            preparation_milliseconds = (time.perf_counter() - started_at) * 1000
            return jsonify({
                'broker': broker_name,
                'order_id': order_id,
                'status_before_cancel': stored_order.status,
                'dry_run': True,
                'request': broker_request.shown(),
                'timing_ms': {
                    'preparation': round(preparation_milliseconds, 3),
                },
            }), 200

        answer = broker_orders.send_cancel(broker_request)
        preparation_milliseconds = (answer.sent_at - started_at) * 1000
        return jsonify({
            'broker': broker_name,
            'order_id': order_id,
            'status_before_cancel': stored_order.status,
            'outcome': answer.outcome,
            'status_message': answer.status_message,
            'broker_response': answer.response_body,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': answer.broker_milliseconds(),
            },
        }), answer.http_status()

    def find_stored_order(self, order_request, order_texts):
        """Finds the one broker whose order book holds the order.

        Args:
            order_request (CancelOrderRequest | ModifyOrderRequest): The validated cancel or modify request, with `order_id` and `broker`.
            order_texts (list): Each broker's hash entry for the order id as Redis holds it, in `broker_names` order.

        Returns:
            tuple: `(broker_name, stored_order)`, where `broker_name` is a string and `stored_order` a `StoredOrder`.

        Raises:
            RefusedRequestError: With HTTP 404 when no broker holds the order, and 409 when more than one does.
        """
        matched_entries = {}
        for position, broker_name in enumerate(self.broker_names):
            requested_broker = order_request.broker
            if requested_broker is not None and broker_name != requested_broker:
                continue
            order_text = order_texts[position]
            if not order_text:
                continue
            try:
                entry = json.loads(order_text)
            except ValueError:
                entry = None
            if isinstance(entry, dict):
                matched_entries[broker_name] = entry

        if not matched_entries:
            raise self.refuse(
                'no broker order book in Redis holds this order_id',
                404,
                order_id=order_request.order_id,
            )
        if len(matched_entries) > 1:
            raise self.refuse(
                'more than one broker holds an order with this order_id, so give broker',
                409,
                order_id=order_request.order_id,
                brokers=list(matched_entries),
            )
        broker_name = list(matched_entries)[0]
        return broker_name, StoredOrder(matched_entries[broker_name])


orders_bp = OrdersBlueprint().blueprint
