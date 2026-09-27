"""
`/api/orders`: today's orders and trades across every broker, and placing, modifying and cancelling an order.

| Route | Does |
| --- | --- |
| `GET /details` | Every broker's orders, from `unified:orders:orders`, kept by `bin/unified/orders/api_order_details` every half second |
| `GET /trades` | Every broker's trades, from `unified:orders:trades`, kept by `bin/unified/orders/api_trade_details` every half second |
| `POST /place` | Places one order at the first broker the configured selector ranks that can take it, reading only Redis before the broker's place-order call |
| `PUT /modify` | Changes one open order at the broker whose order book in Redis holds its order id, or each order of an `orders` list |
| `DELETE /cancel` | Cancels one order at the broker whose order book in Redis holds its order id, or each order of an `orders` list |

`GET /details` and `GET /trades` ask no broker. `POST /place`, `PUT /modify` and `DELETE /cancel` each send exactly one request to one broker per order and never read MongoDB or PostgreSQL, so that the API's own work adds as little as possible to the time the broker takes. A list of modifications or cancels is read from Redis in one round trip like a single one, and its requests go out up to ORDER_SEND_THREADS at once; see `utilities/broker_orders/utilities/order_change_list.py`.

Every Redis read the three order routes make is in this module. What differs between brokers, building the request and reading the answer, is in `unified_broker_interface/utilities/broker_orders/`, whose classes are handed decoded dictionaries and read no store themselves.
"""

import datetime
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor

import redis
from flask import jsonify, request

from unified_broker_interface.blueprints.base import BaseBlueprint
from unified_broker_interface.blueprints.base import authenticated
from unified_broker_interface.utilities.broker_orders.utilities.catalogue_availability import (
    CatalogueAvailability,
)
from unified_broker_interface.utilities.broker_orders.utilities.cancel_order_request import (
    CancelOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.kill_switch import (
    KillSwitch,
)
from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_change_list import (
    OrderChangeList,
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
from unified_broker_interface.utilities.broker_orders.utilities.placement import (
    OrderPlacement,
)
from unified_broker_interface.utilities.broker_orders.utilities.prepared_cancel import (
    PreparedCancel,
)
from unified_broker_interface.utilities.broker_orders.utilities.prepared_modification import (
    PreparedModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)
from unified_broker_interface.utilities.instrument_cache import InstrumentCache
from unified_broker_interface.utilities.order_engine.utilities.daily_order_count import (
    DailyOrderCount,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    IntentHandoff,
)
from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    RateBudget,
)
from unified_broker_interface.utilities.unified_documents import read_document
from utilities.configurations import api_configuration
from utilities.configurations import get_logger

ORDER_SEND_THREADS = 4

ORDER_PLACEMENT_MODES = (
    'direct',
    'engine',
)


class OrdersBlueprint(BaseBlueprint):
    """The `/api/orders` routes: order and trade books from Redis, and placing, modifying and cancelling orders.

    Attributes:
        order_placement (OrderPlacement): Everything an order goes through once Redis has been read: the turn, the broker, the request, the send and the answer.
        broker_names (list): Every broker's name, in the order the brokers take turns; the same list `order_placement` holds.
        broker_orders (dict): Each broker's name to its order class instance; the same dictionary `order_placement` holds.
        broker_selector (BrokerSelector): The algorithm that orders the brokers an order is offered to, named by `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR`; the same object `order_placement` holds.
        connection_warmers (list): One `ConnectionWarmer` per broker named in `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS`, each running on its own daemon thread; the same list `order_placement` holds.
        placement_mode (str): `direct` when this worker sends orders to brokers itself, or `engine` when it hands them to the order engine, named by `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT`.
        order_handoff (IntentHandoff | None): The handoff to the order engine in `engine` mode, and None in `direct` mode, which is what `place_order` branches on.
        instrument_cache (InstrumentCache): This worker's copy of the catalogue data placements and modifications have read under the current warm.
        catalogue_availability (CatalogueAvailability): What turns a "not mapped" refusal into a 503 when the day's catalogue has expired and the next one is not published yet.
        kill_switch (KillSwitch): What decides, from decoded order books and positions, what `POST /flatten` cancels and closes.
        logger (logging.Logger): The logger for failures that do not change an answer.
    """

    name = 'orders'
    routes = [
        ('/details', 'details', ['GET']),
        ('/trades', 'trades', ['GET']),
        ('/place', 'place', ['POST']),
        ('/modify', 'modify', ['PUT']),
        ('/cancel', 'cancel', ['DELETE']),
        ('/flatten', 'flatten', ['POST']),
    ]

    def __init__(self):
        """Builds the blueprint, one order class per broker with no broker connection open yet, and the configured broker selector.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the configured broker selector or the configured order placement mode is not a known one, or the daily order caps cannot be read, so a misspelt name stops the worker from starting rather than routing orders some other way.
        """
        super().__init__()
        self.logger = get_logger('rest_api.orders')
        self.order_placement = OrderPlacement(
            self.logger,
            ORDER_SEND_THREADS + 1,
        )
        self.broker_names = self.order_placement.broker_names
        self.broker_orders = self.order_placement.broker_orders
        self.broker_selector = self.order_placement.broker_selector
        self.connection_warmers = self.order_placement.connection_warmers
        self.placement_mode = api_configuration['order_placement']
        if self.placement_mode not in ORDER_PLACEMENT_MODES:
            known_modes = ', '.join(ORDER_PLACEMENT_MODES)
            raise ValueError(
                f'unknown order placement {self.placement_mode!r}; known modes are {known_modes}'
            )
        self.instrument_cache = InstrumentCache()
        self.catalogue_availability = CatalogueAvailability(self.cache)
        self.order_placement.attach_daily_count(
            DailyOrderCount.from_configuration(self.cache, self.logger),
        )
        self.kill_switch = KillSwitch(self.broker_names)
        self.rate_budget = RateBudget(
            self.cache,
            api_configuration['order_rate_per_second'],
            api_configuration['order_rate_per_broker_per_second'],
            api_configuration['order_rate_wait_seconds'],
            self.logger,
        )
        self.order_handoff = None
        if self.placement_mode == 'engine':
            self.order_handoff = IntentHandoff(
                self.cache,
                api_configuration['order_engine_timeout_seconds'],
            )
        self.order_placement.start_connection_warmers()

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
        return RefusedRequestError.refusal(message, status, **fields)

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

    def take_rate_room(self, broker_name):
        """Takes room in the shared per-broker rate budget for one modification or cancellation, waiting briefly if the last second is full.

        The order engine takes room from the same Redis window before every request it sends, so a busy second of engine orders and API changes together still stays within the limit at each broker.

        Args:
            broker_name (str): The broker the change is going to.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 503 when no room came within the wait, or when Redis could not be read.
        """
        try:
            allowed = self.rate_budget.take(broker_name)
        except redis.RedisError as error:
            raise self.redis_unreadable(error)
        if not allowed:
            raise self.refuse(
                'the order rate budget is full, so this change was not sent; '
                'try again in a moment',
                503,
                broker=broker_name,
            )

    def send_change(self, prepared, started_at):
        """Sends one prepared modification or cancellation, after taking room for it in the rate budget.

        Args:
            prepared (PreparedCancel | PreparedModification): The change to send.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 503 when the rate budget had no room, or Redis could not be read.
        """
        self.take_rate_room(prepared.broker_name)
        return prepared.send(started_at)

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

        All of that describes `direct` placement, which is the default. When `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` is `engine`, the method checks the token and the body itself and then writes the order to `unified:orders:intents:stream` for `bin/unified/orders/order_engine` to place, waiting on `unified:orders:intents:result:<intent_id>` for the answer.
        A `broker` field in the body is removed before the handoff, because the caller never chooses the broker; only `flatten` names one, for a position that can only be closed where it is held.
        The answer carries the same keys with one addition, `intent_id`, and an engine that does not answer in time is reported as outcome `unknown` with HTTP 504, because the order may still be placed.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int), which is 200 when the broker accepted the order or for a dry run, 422 when the broker refused it, 504 when the outcome is unknown, 400 for an order that is not valid, 401 for a missing, wrong or expired access token, 404 for an instrument that is not mapped, and 503 when Redis cannot be read, today's instrument catalogue is not published yet, the order engine is not running, or no broker can take the order.
        """
        started_at = time.perf_counter()
        try:
            body, status = self.place_order(started_at)
        except RefusedRequestError as refusal:
            refusal = self.catalogue_availability.explained(refusal)
            body, status = refusal.body, refusal.status
        return jsonify(body), status

    def place_order(self, started_at):
        """Does the work of `place`, raising a refusal for any request answered without calling a broker.

        Args:
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), for `place` to turn into a JSON response.

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

        if self.order_handoff is not None:
            catalogue_key_prefix = self.catalogue_key_prefix(mapping_date_text)
            instrument_id = self.resolve_instrument_id(
                order,
                mapping_date_text,
                warm_identifier,
                catalogue_key_prefix,
            )
            engine_body = dict(request.get_json(silent=True))
            engine_body.pop('broker', None)
            return self.order_handoff.place(
                engine_body,
                instrument_id,
                started_at,
            )

        rotation = self.order_placement.rotation()
        catalogue_key_prefix = self.catalogue_key_prefix(mapping_date_text)
        instrument_id = self.resolve_instrument_id(
            order,
            mapping_date_text,
            warm_identifier,
            catalogue_key_prefix,
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

        instrument = Instrument.decoded(
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
        return self.order_placement.place(
            order,
            instrument,
            rotation,
            selector_replies,
            login_texts,
            settings_texts,
            started_at,
        )

    def catalogue_key_prefix(self, mapping_date_text):
        """The prefix of today's catalogue keys, refusing the order when nothing has been mapped.

        Args:
            mapping_date_text (str | None): The mapping date as Redis holds it.

        Returns:
            str: The prefix, such as `unified:catalogue:2026-09-15:`.

        Raises:
            RefusedRequestError: With HTTP 503 when no instruments have been mapped yet.
        """
        if not mapping_date_text:
            raise self.refuse('no instruments have been mapped yet', 503)
        return f'unified:catalogue:{mapping_date_text}:'

    def resolve_instrument_id(
        self,
        order,
        mapping_date_text,
        warm_identifier,
        catalogue_key_prefix,
    ):
        """Finds the instrument the order is for, by its id or by the identity fields that name it.

        An order that names an id needs no lookup. One that names identity fields is looked up in this worker's cache first, and only then in the catalogue, which costs the one Redis round trip an order can make beyond its two pipelines.

        This is the only place the lookup happens. In engine mode the route resolves the instrument here and writes the id into the intent, so the rule that decides an identity is unknown or ambiguous lives in one place rather than in both this module and the order engine.

        Args:
            order (PlaceOrderRequest): The validated order.
            mapping_date_text (str): The mapping date as Redis holds it.
            warm_identifier (str | None): The current warm's identifier.
            catalogue_key_prefix (str): The prefix of today's catalogue keys.

        Returns:
            str: The instrument id.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read, 404 when no instrument matches, and 400 when more than one does.
        """
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
        return instrument_id

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

        A body holding an `orders` list is the list form, answered by `modify_order_list`.

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
        body = request.get_json(silent=True)
        if isinstance(body, dict) and 'orders' in body:
            return self.modify_order_list(access_token, body, started_at)

        try:
            modify_request = ModifyOrderRequest(
                body,
                request.args,
                self.broker_names,
            )
        except InvalidOrderError as error:
            raise self.refuse(str(error), 400)

        state = self.read_order_state(
            [
                modify_request.order_id,
            ],
            True,
        )
        self.check_access_token(access_token, state['token_document_text'])
        prepared = self.prepare_modification(modify_request, state)
        if modify_request.dry_run:
            answer_body, status = prepared.dry_run_answer(started_at)
        else:
            answer_body, status = self.send_change(prepared, started_at)
        return jsonify(answer_body), status

    def modify_order_list(self, access_token, body, started_at):
        """Modifies every order of a list, answering each on its own.

        Every order's entries and the catalogue markers are read from Redis in one round trip, each order is checked as a single modification is, and the modifications that pass are sent to their brokers, up to ORDER_SEND_THREADS at once.

        Args:
            access_token (str): The `access-token` header.
            body (dict): The decoded JSON body, which holds `orders`.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The Flask JSON response `{"results": [...]}` (flask.Response) and the HTTP status 200.

        Raises:
            RefusedRequestError: With 400 for an invalid list, 401 for a wrong or expired access token, and 503 when Redis cannot be read.
        """
        try:
            order_list = OrderChangeList(
                body,
                request.args,
                ModifyOrderRequest,
                self.broker_names,
            )
        except InvalidOrderError as error:
            raise self.refuse(str(error), 400)
        state = self.read_order_state(order_list.order_ids(), True)
        self.check_access_token(access_token, state['token_document_text'])
        self.warm_order_instruments(order_list, state)

        prepared_entries = []
        for entry in order_list.entries:
            if isinstance(entry, RefusedRequestError):
                prepared_entries.append(entry)
                continue
            try:
                prepared_entries.append(self.prepare_modification(entry, state))
            except RefusedRequestError as refusal:
                prepared_entries.append(refusal)
        answers = self.answer_prepared_list(prepared_entries, order_list.dry_run, started_at)
        return jsonify({
            'results': order_list.results(answers),
        }), 200

    def warm_order_instruments(self, order_list, state):
        """Reads the catalogue entries of every order in a modify list into this worker's instrument cache, in at most two round trips.

        `resolve_order_instrument` reads an order's token candidates and then the candidates' identities, handles and contract sizes, each read skipped when this worker already holds it. Reading them here for the whole list first means each order then finds them held, so the list costs the same round trips however many orders it has. Nothing here refuses anything: an order that cannot be found or checked is skipped, and `prepare_modification` refuses it with the usual status.

        Args:
            order_list (OrderChangeList): The validated list.
            state (dict): What `read_order_state` read with the catalogue markers.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read.
        """
        mapping_date_text = state['mapping_date_text']
        warm_identifier = state['warm_identifier']
        if not mapping_date_text:
            return
        catalogue_key_prefix = f'unified:catalogue:{mapping_date_text}:'

        wanted_tokens = []
        for entry in order_list.entries:
            if isinstance(entry, RefusedRequestError):
                continue
            try:
                broker_name, stored_order = self.find_stored_order(entry, state['order_texts'][entry.order_id])
                modification = OrderModification(entry, stored_order)
            except (RefusedRequestError, InvalidOrderError, UnmodifiableOrderError, OrderNotReadyError):
                continue
            broker_token = modification.instrument_token
            if broker_token is None or (broker_name, broker_token) in wanted_tokens:
                continue
            wanted_tokens.append((broker_name, broker_token))

        candidates_by_token = {}
        unread_tokens = []
        for broker_name, broker_token in wanted_tokens:
            candidates_text = self.instrument_cache.token_candidates_text(
                mapping_date_text,
                warm_identifier,
                broker_name,
                broker_token,
            )
            if candidates_text is None:
                unread_tokens.append((broker_name, broker_token))
            else:
                candidates_by_token[(broker_name, broker_token)] = candidates_text
        if unread_tokens:
            try:
                pipeline = self.cache.pipeline(transaction=False)
                for broker_name, broker_token in unread_tokens:
                    pipeline.hget(catalogue_key_prefix + 'tokens:' + broker_name, broker_token)
                replies = pipeline.execute()
            except redis.RedisError as error:
                raise self.redis_unreadable(error)
            for index, token_key in enumerate(unread_tokens):
                candidates_text = replies[index]
                if not candidates_text:
                    continue
                broker_name, broker_token = token_key
                self.instrument_cache.keep_token_candidates(
                    mapping_date_text,
                    warm_identifier,
                    broker_name,
                    broker_token,
                    candidates_text,
                )
                candidates_by_token[token_key] = candidates_text

        unread_ids = []
        for candidates_text in candidates_by_token.values():
            for candidate_id in candidates_text.split(','):
                if not candidate_id or candidate_id in unread_ids:
                    continue
                if self.instrument_cache.instrument(mapping_date_text, warm_identifier, candidate_id) is None:
                    unread_ids.append(candidate_id)
        if not unread_ids:
            return
        try:
            pipeline = self.cache.pipeline(transaction=False)
            for candidate_id in unread_ids:
                pipeline.hget(catalogue_key_prefix + 'identity', candidate_id)
                pipeline.hget(catalogue_key_prefix + 'order_handles', candidate_id)
                pipeline.hget(catalogue_key_prefix + 'contract_sizes', candidate_id)
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise self.redis_unreadable(error)
        for index, candidate_id in enumerate(unread_ids):
            texts = (
                replies[3 * index],
                replies[3 * index + 1],
                replies[3 * index + 2],
            )
            try:
                Instrument.decoded(candidate_id, texts[0], texts[1], texts[2])
            except RefusedRequestError:
                continue
            self.instrument_cache.keep_instrument(
                mapping_date_text,
                warm_identifier,
                candidate_id,
                texts[0],
                texts[1],
                texts[2],
            )

    def answer_prepared_list(self, prepared_entries, dry_run, started_at):
        """Answers every entry of a list: a refusal as it is, and a prepared change by showing or sending it.

        The changes to send go out on up to ORDER_SEND_THREADS threads at once, and a single one is sent on the request's own thread. Nothing is retried.

        Args:
            prepared_entries (list): One entry per item, in order: a `PreparedCancel` or `PreparedModification`, or a `RefusedRequestError`.
            dry_run (bool): Whether to show every prepared change instead of sending it.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            list: One `(body, status)` pair per entry, in the same order.
        """
        answers = [None] * len(prepared_entries)
        positions_to_send = []
        for position, entry in enumerate(prepared_entries):
            if isinstance(entry, RefusedRequestError):
                answers[position] = (entry.body, entry.status)
            elif dry_run:
                answers[position] = entry.dry_run_answer(started_at)
            else:
                positions_to_send.append(position)

        if len(positions_to_send) == 1:
            position = positions_to_send[0]
            answers[position] = self.send_prepared(prepared_entries[position], started_at)
        elif positions_to_send:
            threads = min(ORDER_SEND_THREADS, len(positions_to_send))
            with ThreadPoolExecutor(max_workers=threads, thread_name_prefix='order') as executor:
                futures = {}
                for position in positions_to_send:
                    futures[position] = executor.submit(self.send_prepared, prepared_entries[position], started_at)
                for position, future in futures.items():
                    answers[position] = future.result()
        return answers

    def send_prepared(self, prepared, started_at):
        """Sends one prepared change of a list, answering an unexpected failure instead of raising it.

        The other changes of the list may already have been sent, so one failure must not hide their answers behind a 500.

        Args:
            prepared (PreparedCancel | PreparedModification): The change to send.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int): the broker's answer, or 504 when sending failed unexpectedly and whether the broker received the change is unknown.
        """
        try:
            return self.send_change(prepared, started_at)
        except RefusedRequestError as refusal:
            return refusal.body, refusal.status
        except Exception as error:
            self.logger.exception(
                'sending a change to %s order %s failed unexpectedly',
                prepared.broker_name,
                prepared.order_id,
            )
            return {
                'error': f'sending failed unexpectedly, so whether the broker received it is unknown: {error}',
                'broker': prepared.broker_name,
                'order_id': prepared.order_id,
            }, 504

    def prepare_modification(self, modify_request, state):
        """Checks one modification against the order books, the broker and the instrument, and builds its request.

        Args:
            modify_request (ModifyOrderRequest): The validated modification.
            state (dict): What `read_order_state` read with the catalogue markers, holding this order's entries.

        Returns:
            PreparedModification: The modification, ready to show or send.

        Raises:
            RefusedRequestError: For every reason `modify` documents for answering without calling a broker.
        """
        order_id = modify_request.order_id
        broker_name, stored_order = self.find_stored_order(
            modify_request,
            state['order_texts'][order_id],
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
        login = broker_orders.decode_login(state['login_texts'][position])
        settings = broker_orders.decode_settings(state['settings_texts'][position])
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
            state['mapping_date_text'],
            state['warm_identifier'],
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
        return PreparedModification(broker_orders, order_id, stored_order, instrument_id, broker_request)

    def read_order_state(self, order_ids, with_catalogue):
        """Reads, in one Redis round trip, everything a modify or cancel of some orders checks before calling a broker.

        Args:
            order_ids (list): The broker order ids to look up in every broker's order book.
            with_catalogue (bool): Whether to read the catalogue's mapping date and warm identifier as well, which a modify needs to find the order's instrument.

        Returns:
            dict: `token_document_text`, `mapping_date_text` and `warm_identifier` (str or None, the last two None unless read), `login_texts` and `settings_texts` (one entry per broker, in `broker_names` order), and `order_texts`, mapping each order id to its entry in each broker's order book, in `broker_names` order.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read.
        """
        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', 'unified_broker_interface')
            if with_catalogue:
                pipeline.get('unified:catalogue:current_date')
                pipeline.get('unified:catalogue:warm_identifier')
            pipeline.hmget('last_login', self.broker_names)
            pipeline.hmget('settings', self.broker_names)
            for order_id in order_ids:
                for broker_name in self.broker_names:
                    pipeline.hget(f'{broker_name}:orders:orders', order_id)
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise self.redis_unreadable(error)

        state = {
            'token_document_text': replies[0],
            'mapping_date_text': None,
            'warm_identifier': None,
        }
        position = 1
        if with_catalogue:
            state['mapping_date_text'] = replies[1]
            state['warm_identifier'] = replies[2]
            position = 3
        state['login_texts'] = replies[position]
        state['settings_texts'] = replies[position + 1]
        position = position + 2
        broker_count = len(self.broker_names)
        order_texts = {}
        for order_id in order_ids:
            order_texts[order_id] = replies[position:position + broker_count]
            position = position + broker_count
        state['order_texts'] = order_texts
        return state

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
                instrument = Instrument.decoded(
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

        A body holding an `orders` list is the list form, answered by `cancel_order_list`.

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
        body = request.get_json(silent=True)
        if isinstance(body, dict) and 'orders' in body:
            return self.cancel_order_list(access_token, body, started_at)

        try:
            cancel_request = CancelOrderRequest(
                body,
                request.args,
                self.broker_names,
            )
        except InvalidOrderError as error:
            raise self.refuse(str(error), 400)

        state = self.read_order_state(
            [
                cancel_request.order_id,
            ],
            False,
        )
        self.check_access_token(access_token, state['token_document_text'])
        prepared = self.prepare_cancel(cancel_request, state)
        if cancel_request.dry_run:
            answer_body, status = prepared.dry_run_answer(started_at)
        else:
            answer_body, status = self.send_change(prepared, started_at)
        return jsonify(answer_body), status

    def cancel_order_list(self, access_token, body, started_at):
        """Cancels every order of a list, answering each on its own.

        Every order's entries are read from Redis in one round trip, each order is checked as a single cancel is, and the cancels that pass are sent to their brokers, up to ORDER_SEND_THREADS at once.

        Args:
            access_token (str): The `access-token` header.
            body (dict): The decoded JSON body, which holds `orders`.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The Flask JSON response `{"results": [...]}` (flask.Response) and the HTTP status 200.

        Raises:
            RefusedRequestError: With 400 for an invalid list, 401 for a wrong or expired access token, and 503 when Redis cannot be read.
        """
        try:
            order_list = OrderChangeList(
                body,
                request.args,
                CancelOrderRequest,
                self.broker_names,
            )
        except InvalidOrderError as error:
            raise self.refuse(str(error), 400)
        state = self.read_order_state(order_list.order_ids(), False)
        self.check_access_token(access_token, state['token_document_text'])

        prepared_entries = []
        for entry in order_list.entries:
            if isinstance(entry, RefusedRequestError):
                prepared_entries.append(entry)
                continue
            try:
                prepared_entries.append(self.prepare_cancel(entry, state))
            except RefusedRequestError as refusal:
                prepared_entries.append(refusal)
        answers = self.answer_prepared_list(prepared_entries, order_list.dry_run, started_at)
        return jsonify({
            'results': order_list.results(answers),
        }), 200

    def prepare_cancel(self, cancel_request, state):
        """Checks one cancel against the order books and the broker's login, and builds its request.

        Args:
            cancel_request (CancelOrderRequest): The validated cancel.
            state (dict): What `read_order_state` read, holding this order's entries.

        Returns:
            PreparedCancel: The cancel, ready to show or send.

        Raises:
            RefusedRequestError: When no broker or more than one holds the order, the order has finished, or the broker's login, settings or the order's details are missing.
        """
        order_id = cancel_request.order_id
        broker_name, stored_order = self.find_stored_order(
            cancel_request,
            state['order_texts'][order_id],
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
        login = broker_orders.decode_login(state['login_texts'][position])
        settings = broker_orders.decode_settings(state['settings_texts'][position])
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
        return PreparedCancel(broker_orders, order_id, stored_order, broker_request)

    def flatten(self):
        """Cancels every open order at every broker, waits for the cancels, then closes every position.

        This is the panic button. The JSON body must carry `confirm` set to `FLATTEN`, which exists so that a stray request cannot unwind an account, and may carry `dry_run` to report what would happen without sending anything.

        The order of the two halves is the whole point. A resting stop or target that is still live when its position is closed will fill afterwards and open a new position the other way, turning an attempt to go flat into a trade nobody chose. So every open order is cancelled first, the brokers' own order books are re-read until they agree the orders are gone or `UNIFIED_BROKER_INTERFACE_API_ORDER_FLATTEN_WAIT_SECONDS` runs out, and only then are closing orders sent.

        Positions are read from each broker's own `<broker>:portfolio:positions` rather than from the merged unified document, because a closing order has to go to the broker that actually holds the position, and the unified document deliberately merges a position across brokers.

        A failure to cancel does not stop the closing half, but it is reported and the answer says the account may not be flat. Nothing is retried: a panic button that retries is a panic button that takes longer to finish.

        An accepted closing order is not taken as proof that the position is gone, because a broker can accept an order that the exchange then rejects. After the closes, the brokers' positions are re-read until every closed position shows zero or the same wait runs out, and `flat` is true only when they all do.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int), which is 200 when everything asked for was done or for a dry run, 207 when some part failed or a closed position was still held after the wait, 400 without the confirmation, 401 for a missing, wrong or expired access token, and 503 when Redis cannot be read.
        """
        started_at = time.perf_counter()
        try:
            body, status = self.flatten_everything(started_at)
        except RefusedRequestError as refusal:
            body, status = refusal.body, refusal.status
        return jsonify(body), status

    def flatten_everything(self, started_at):
        """Does the work of `flatten`, raising a refusal for anything answered without calling a broker.

        Args:
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a request answered without calling a broker.
        """
        access_token = request.headers.get('access-token')
        if not access_token:
            raise self.refuse('Access token is required', 401)
        body = request.get_json(silent=True) or {}
        if body.get('confirm') != 'FLATTEN':
            raise self.refuse(
                'flattening cancels every order and closes every position, so '
                'it needs confirm set to FLATTEN',
                400,
            )
        dry_run = bool(body.get('dry_run'))

        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', 'unified_broker_interface')
            pipeline.hmget('last_login', self.broker_names)
            pipeline.hmget('settings', self.broker_names)
            for broker_name in self.broker_names:
                pipeline.hgetall(f'{broker_name}:orders:orders')
            for broker_name in self.broker_names:
                pipeline.hgetall(f'{broker_name}:portfolio:positions')
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise self.redis_unreadable(error)
        self.check_access_token(access_token, replies[0])
        login_texts = replies[1]
        settings_texts = replies[2]
        broker_count = len(self.broker_names)
        order_books = self.decode_books(replies[3:3 + broker_count])
        position_books = self.decode_books(
            replies[3 + broker_count:3 + broker_count * 2],
        )

        cancelling = self.kill_switch.orders_to_cancel(order_books)
        closing = self.kill_switch.positions_to_close(position_books)
        if dry_run:
            return {
                'dry_run': True,
                'would_cancel': self.shown_cancels(cancelling),
                'would_close': closing,
                'timing_ms': {
                    'preparation': round(
                        (time.perf_counter() - started_at) * 1000,
                        3,
                    ),
                },
            }, 200

        cancelled = self.cancel_every_order(
            cancelling,
            login_texts,
            settings_texts,
        )
        still_open = self.wait_for_cancels(cancelling)
        closed = self.close_every_position(closing, started_at)
        still_held = self.wait_for_positions(closed)

        # A close that was sent and refused leaves the position exactly where it was, so it counts
        # as a failure although the request itself went out. A cancel is judged only on whether the
        # order is still live, which the wait above has already established.
        failures = [answer for answer in cancelled if not answer['sent']]
        for answer in closed:
            if not answer['sent'] or answer.get('outcome') != 'accepted':
                failures.append(answer)
        flat = not failures and not still_open and not still_held
        status = 200 if flat else 207
        return {
            'cancelled': cancelled,
            'still_open_after_waiting': [
                f'{broker}:{order_id}' for broker, order_id in still_open
            ],
            'closed': closed,
            'positions_still_open_after_waiting': [
                f'{broker}:{position_key}'
                for broker, position_key in still_held
            ],
            'flat': flat,
            'timing_ms': {
                'preparation': round(
                    (time.perf_counter() - started_at) * 1000,
                    3,
                ),
            },
        }, status

    def decode_books(self, replies):
        """Each broker's hash of JSON entries, decoded, by broker name.

        Args:
            replies (list): One `HGETALL` reply per broker, in `broker_names` order.

        Returns:
            dict: Broker names to their decoded entries.
        """
        books = {}
        for position, broker_name in enumerate(self.broker_names):
            entries = replies[position] or {}
            decoded = {}
            for key, text in entries.items():
                try:
                    entry = json.loads(text)
                except (TypeError, ValueError):
                    continue
                if isinstance(entry, dict):
                    decoded[key] = entry
            books[broker_name] = decoded
        return books

    def shown_cancels(self, cancelling):
        """The orders that would be cancelled, without the brokers' whole stored entries.

        Args:
            cancelling (list): What `KillSwitch.orders_to_cancel` returned.

        Returns:
            list: One dictionary per order, with `broker`, `order_id` and `status`.
        """
        shown = []
        for order in cancelling:
            shown.append({
                'broker': order['broker'],
                'order_id': order['order_id'],
                'status': order['status'],
            })
        return shown

    def cancel_every_order(self, cancelling, login_texts, settings_texts):
        """Sends a cancel for every open order, reporting each rather than stopping at the first failure.

        Args:
            cancelling (list): What `KillSwitch.orders_to_cancel` returned.
            login_texts (list): Every broker's login as Redis holds it.
            settings_texts (list): Every broker's settings as Redis holds them.

        Returns:
            list: One dictionary per order, with `broker`, `order_id`, `sent`, `outcome` and `status_message`.
        """
        answers = []
        for order in cancelling:
            broker_name = order['broker']
            broker_orders = self.broker_orders[broker_name]
            position = self.broker_names.index(broker_name)
            login = broker_orders.decode_login(login_texts[position])
            settings = broker_orders.decode_settings(settings_texts[position])
            answers.append(self.cancel_one_order(
                broker_orders,
                order,
                login,
                settings,
            ))
        return answers

    def cancel_one_order(self, broker_orders, order, login, settings):
        """Cancels one order and reports what happened, without raising.

        Args:
            broker_orders (BrokerOrders): The broker's order class.
            order (dict): One entry from `KillSwitch.orders_to_cancel`.
            login (object): The broker's decoded login.
            settings (dict): The broker's decoded settings.

        Returns:
            dict: What happened, with `broker`, `order_id`, `sent`, `outcome` and `status_message`.
        """
        answer = {
            'broker': order['broker'],
            'order_id': order['order_id'],
            'sent': False,
            'outcome': None,
            'status_message': None,
        }
        problem = broker_orders.cancel_problem(login, settings)
        if problem is not None:
            answer['status_message'] = problem
            return answer
        try:
            broker_request = broker_orders.build_cancel_request(
                order['order_id'],
                StoredOrder(order['entry']),
                login,
                settings,
            )
        except (OrderNotReadyError, KeyError, TypeError, ValueError) as error:
            answer['status_message'] = f'the cancel could not be built: {error}'
            return answer
        try:
            self.take_rate_room(order['broker'])
        except RefusedRequestError as refusal:
            answer['status_message'] = refusal.body.get('error')
            return answer
        try:
            sent = broker_orders.send_cancel(broker_request)
        except Exception as error:
            answer['status_message'] = f'the cancel could not be sent: {error}'
            return answer
        answer['sent'] = True
        answer['outcome'] = sent.outcome
        answer['status_message'] = sent.status_message
        return answer

    def wait_for_cancels(self, cancelling):
        """Re-reads the brokers' order books until the cancelled orders are gone, or time runs out.

        Waiting matters more than being quick. Closing a position while one of its protective orders is still live at the exchange re-opens the position in the other direction, which is the failure this whole route exists to avoid.

        Args:
            cancelling (list): What `KillSwitch.orders_to_cancel` returned.

        Returns:
            list: The `(broker, order_id)` pairs still live when the wait ended.
        """
        if not cancelling:
            return []
        deadline = time.perf_counter() + api_configuration[
            'order_flatten_wait_seconds'
        ]
        still_open = [
            (order['broker'], order['order_id']) for order in cancelling
        ]
        while still_open and time.perf_counter() < deadline:
            time.sleep(0.25)
            try:
                pipeline = self.cache.pipeline(transaction=False)
                for broker_name in self.broker_names:
                    pipeline.hgetall(f'{broker_name}:orders:orders')
                order_books = self.decode_books(pipeline.execute())
            except redis.RedisError:
                continue
            still_open = self.kill_switch.still_open(order_books, cancelling)
        return still_open

    def wait_for_positions(self, closed):
        """Re-reads the brokers' positions until every accepted close shows the position gone, or time runs out.

        Only closes the broker accepted are waited for. A close that was not sent or was refused is already a failure in the answer, and waiting for its position would only delay the answer by the whole wait.

        Args:
            closed (list): What `close_every_position` returned.

        Returns:
            list: The `(broker, position_key)` pairs still held when the wait ended.
        """
        accepted = []
        for answer in closed:
            if answer['sent'] and answer.get('outcome') == 'accepted':
                accepted.append(answer)
        if not accepted:
            return []
        deadline = time.perf_counter() + api_configuration[
            'order_flatten_wait_seconds'
        ]
        still_held = [
            (answer['broker'], answer['position_key']) for answer in accepted
        ]
        while still_held and time.perf_counter() < deadline:
            time.sleep(0.25)
            try:
                pipeline = self.cache.pipeline(transaction=False)
                for broker_name in self.broker_names:
                    pipeline.hgetall(f'{broker_name}:portfolio:positions')
                position_books = self.decode_books(pipeline.execute())
            except redis.RedisError:
                continue
            still_held = self.kill_switch.still_held(position_books, accepted)
        return still_held

    def close_every_position(self, closing, started_at):
        """Sends a closing order for every position that is not flat, at the broker holding it.

        Args:
            closing (list): What `KillSwitch.positions_to_close` returned.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            list: One dictionary per position, with what was sent and what happened.
        """
        answers = []
        for position in closing:
            answers.append(self.close_one_position(position, started_at))
        return answers

    def close_one_position(self, position, started_at):
        """Closes one position at the broker holding it, without raising.

        Args:
            position (dict): One entry from `KillSwitch.positions_to_close`.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            dict: What happened, with the position, `sent`, `outcome` and `status_message`.
        """
        answer = dict(position)
        answer['sent'] = False
        answer['outcome'] = None
        answer['status_message'] = None
        instrument_id = self.instrument_for_broker_token(
            position['broker'],
            position['instrument_token'],
        )
        if instrument_id is None:
            answer['status_message'] = (
                "the broker's token does not name exactly one mapped "
                'instrument, so this position was not closed'
            )
            return answer
        body = {
            'instrument_id': instrument_id,
            'transaction_type': position['transaction_type'],
            'product': self.closing_product(position['product']),
            'order_type': 'MARKET',
            'quantity': position['close_quantity'],
        }
        try:
            sent, status = self.place_closing_order(
                body,
                instrument_id,
                position['broker'],
                started_at,
            )
        except RefusedRequestError as refusal:
            answer['status_message'] = refusal.body.get('error')
            return answer
        except Exception as error:
            answer['status_message'] = f'the close could not be sent: {error}'
            return answer
        answer['sent'] = True
        answer['outcome'] = sent.get('outcome')
        answer['order_id'] = sent.get('order_id')
        answer['status_message'] = sent.get('status_message')
        answer['http_status'] = status
        return answer

    def closing_product(self, product):
        """The product a closing order carries, on the vocabulary `POST /place` takes.

        Args:
            product (str | None): The position's product, on the shared vocabulary.

        Returns:
            str: `CNC`, `MIS` or `NRML`.
        """
        named = str(product or '').lower()
        if named == 'delivery':
            return 'CNC'
        if named == 'intraday':
            return 'MIS'
        return 'NRML'

    def instrument_for_broker_token(self, broker_name, broker_token):
        """The one instrument a broker's token names today, or None when it is not exactly one.

        Args:
            broker_name (str): The broker.
            broker_token (str | None): The broker's own instrument token.

        Returns:
            str | None: The instrument id.
        """
        if not broker_token:
            return None
        try:
            stored = self.cache.hget(
                'unified:broker_tokens',
                f'{broker_name}:{broker_token}',
            )
        except redis.RedisError:
            return None
        if not stored:
            return None
        try:
            instrument_ids = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(instrument_ids, list) or len(instrument_ids) != 1:
            return None
        return str(instrument_ids[0])

    def place_closing_order(self, body, instrument_id, broker_name, started_at):
        """Places one closing order at a named broker, through whichever placement mode is configured.

        In engine mode the body handed to the engine names the broker in `broker`, which the plain `simple` type sends the order to, and marks the order with `closes_position` so that it may use the part of the broker's daily cap kept for exits.

        Args:
            body (dict): The order body.
            instrument_id (str): The instrument.
            broker_name (str): The broker holding the position.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = PlaceOrderRequest(body)
        if self.order_handoff is not None:
            engine_body = dict(body)
            engine_body['broker'] = broker_name
            engine_body['synthetic'] = {
                'type': 'simple',
                'closes_position': True,
            }
            return self.order_handoff.place(
                engine_body,
                instrument_id,
                started_at,
            )
        rotation = self.order_placement.rotation()
        catalogue_key_prefix = self.catalogue_key_prefix(
            self.cache.get('unified:catalogue:current_date'),
        )
        pipeline = self.cache.pipeline(transaction=False)
        pipeline.hget(catalogue_key_prefix + 'identity', instrument_id)
        pipeline.hget(catalogue_key_prefix + 'order_handles', instrument_id)
        pipeline.hget(catalogue_key_prefix + 'contract_sizes', instrument_id)
        pipeline.hmget('last_login', self.broker_names)
        pipeline.hmget('settings', self.broker_names)
        replies = pipeline.execute()
        instrument = Instrument.decoded(
            instrument_id,
            replies[0],
            replies[1],
            replies[2],
        )
        prepared = self.order_placement.prepare(
            order,
            instrument,
            rotation,
            [],
            replies[3],
            replies[4],
            broker_name,
        )
        return self.order_placement.send(prepared, started_at)

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
