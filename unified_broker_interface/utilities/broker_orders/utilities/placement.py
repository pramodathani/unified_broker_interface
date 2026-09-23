"""Choosing the broker for one order, building its request, sending it and reading the answer.

This is the half of order placement that reads no store. The caller reads Redis and hands the decoded texts in, which is what lets both the REST API worker and the order engine place an order the same way, through the same code, and answer with the same body.

The answer bodies built here are the REST API's own. That is a deliberate compromise: the alternative is for the order engine to carry its own copy of the same fifteen lines, and the whole point of the engine is that a caller cannot tell which process placed the order.
"""

import time

from unified_broker_interface.utilities.broker_orders.utilities.connection_warmer import (
    ConnectionWarmer,
)
from unified_broker_interface.utilities.broker_orders.utilities.prepared_placement import (
    PreparedPlacement,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.broker_orders.utilities.registry import (
    BROKER_ORDER_CLASSES,
)
from unified_broker_interface.utilities.broker_selection.utilities.registry import (
    BROKER_SELECTOR_CLASSES,
)
from utilities.configurations import api_configuration


class OrderPlacement:
    """Everything an order goes through after Redis has been read: the turn, the broker, the request, the send and the answer.

    One instance is built per gunicorn worker and one per order engine. It opens no store connection and makes no network call except the broker's own, so the round trips an order costs can still be counted by reading the caller.

    Attributes:
        broker_names (list): Every broker's name, in the order the brokers take turns.
        broker_orders (dict): Each broker's name to its order class instance, built once.
        broker_selector (BrokerSelector): The algorithm that orders the brokers an order is offered to, named by `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR`.
        connection_warmers (list): One `ConnectionWarmer` per broker named in `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS`, each running on its own daemon thread.
        logger (logging.Logger): The logger for failures that do not change an answer.
    """

    def __init__(self, logger):
        """Builds one order class per broker with no broker connection open yet, and the configured broker selector.

        Args:
            logger (logging.Logger): The logger for failures that do not change an answer.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the configured broker selector is not a known one, so a misspelt name stops the worker from starting rather than routing orders some other way.
        """
        self.logger = logger
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
        self.connection_warmers = []

    def start_connection_warmers(self):
        """Starts a connection warmer for each broker named in `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS`.

        Warming only saves time, so nothing about it may stop the caller: an unknown broker name is logged and ignored, and any other failure is logged and leaves warming off. A broker without a `WARM_URL`, such as Kotak, is pinged only once a request has named its host.

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
            raise RefusedRequestError.refusal(message, 503)
        return rotation

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
            raise RefusedRequestError.refusal(
                f'the contract size of this {instrument.segment} instrument is not trusted today ({status}), so no order is sent',
                503,
                instrument_id=instrument.instrument_id,
                contract_size_status=status,
            )
        problem = order.contract_lot_problem(units_per_lot)
        if problem is not None:
            raise RefusedRequestError.refusal(problem, 400)

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
                broker_orders.decode_login(login_texts[position]),
                broker_orders.decode_settings(settings_texts[position]),
            )
            if reason is None:
                return broker_orders, skipped
            skipped.append({
                'broker': broker_name,
                'reason': reason,
            })
        raise RefusedRequestError.refusal(
            'no broker can take this order',
            503,
            instrument_id=instrument.instrument_id,
            skipped=skipped,
        )

    def choose_named_broker(
        self,
        order,
        instrument,
        broker_name,
        login_texts,
        settings_texts,
    ):
        """Uses the broker the caller named, rather than the one the selector would rank first.

        Closing a position has to go to the broker that holds it, and every leg of a bracket has to go to the broker its entry went to. Neither is something a selector can decide, so both name the broker instead.

        The broker still has to be able to take the order. Skipping that check would send an order to a broker whose market listing does not cover the instrument, which fails at the broker rather than here and with a worse message.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            broker_name (str): The broker the order must go to.
            login_texts (list): Every broker's login as Redis holds it, in `broker_names` order.
            settings_texts (list): Every broker's settings as Redis holds them, in `broker_names` order.

        Returns:
            tuple: `(broker_orders, skipped)`, where `skipped` is always empty because no broker was passed over.

        Raises:
            RefusedRequestError: With HTTP 503 when the named broker is not one this API knows, or cannot take the order.
        """
        broker_orders = self.broker_orders.get(broker_name)
        if broker_orders is None:
            raise RefusedRequestError.refusal(
                f'{broker_name} is not a broker this API places orders at',
                503,
                broker=broker_name,
            )
        position = self.broker_names.index(broker_name)
        reason = broker_orders.place_skip_reason(
            order,
            instrument,
            instrument.handles.get(broker_name),
            broker_orders.decode_login(login_texts[position]),
            broker_orders.decode_settings(settings_texts[position]),
        )
        if reason is not None:
            raise RefusedRequestError.refusal(
                f'{broker_name} cannot take this order: {reason}',
                503,
                broker=broker_name,
                instrument_id=instrument.instrument_id,
            )
        return broker_orders, []

    def prepare(
        self,
        order,
        instrument,
        rotation,
        selector_replies,
        login_texts,
        settings_texts,
        broker_name=None,
    ):
        """Chooses the broker and builds the request, without sending anything.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The instrument the order is for.
            rotation (list): The broker names not excluded by configuration.
            selector_replies (list): The replies to the commands the broker selector queued, in the order it queued them.
            login_texts (list): Every broker's login as Redis holds it, in `broker_names` order.
            settings_texts (list): Every broker's settings as Redis holds them, in `broker_names` order.
            broker_name (str | None): The broker the order must go to, or None to let the selector choose.

        Returns:
            PreparedPlacement: The chosen broker and the request built for it.

        Raises:
            RefusedRequestError: With HTTP 400 when orders are not sent for the instrument's segment or a quantity or price does not fit the instrument, 503 when the contract's size is not trusted today or no broker can take the order.
        """
        if not instrument.is_tradeable():
            message = f'orders are not sent for {instrument.segment} instruments'
            raise RefusedRequestError.refusal(message, 400)
        self.check_contract_size(order, instrument)

        if broker_name is None:
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
        else:
            broker_orders, skipped = self.choose_named_broker(
                order,
                instrument,
                broker_name,
                login_texts,
                settings_texts,
            )
        broker_name = broker_orders.BROKER_NAME
        position = self.broker_names.index(broker_name)
        handle = instrument.handles.get(broker_name)
        login = broker_orders.decode_login(login_texts[position])
        settings = broker_orders.decode_settings(settings_texts[position])

        size_problem = None
        if instrument.is_securities_market():
            size_problem = order.lot_size_problem(handle)
        if size_problem is None:
            size_problem = order.tick_size_problem(instrument.handles)
        if size_problem is not None:
            raise RefusedRequestError.refusal(size_problem, 400)

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
        identifier_sent = None
        if isinstance(handle, dict):
            identifier_sent = handle.get(broker_orders.IDENTIFIER_FIELD)
        return PreparedPlacement(
            instrument.instrument_id,
            broker_orders,
            broker_request,
            skipped,
            identifier_sent,
        )

    def dry_run_answer(self, prepared_placement, started_at):
        """Answers with the request that would have been sent, without sending it.

        Args:
            prepared_placement (PreparedPlacement): The chosen broker and its built request.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), which is always 200.
        """
        preparation_milliseconds = (time.perf_counter() - started_at) * 1000
        return {
            'broker': prepared_placement.broker_name,
            'instrument_id': prepared_placement.instrument_id,
            'tag': prepared_placement.broker_request.tag,
            'dry_run': True,
            'request': prepared_placement.broker_request.shown(),
            'skipped': prepared_placement.skipped,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
            },
        }, 200

    def send(self, prepared_placement, started_at):
        """Sends the prepared order to its broker and reads the answer.

        Args:
            prepared_placement (PreparedPlacement): The chosen broker and its built request.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), which is 200 when the broker accepted the order, 422 when it refused it and 504 when the outcome is unknown.
        """
        broker_orders = prepared_placement.broker_orders
        answer = broker_orders.send_place(prepared_placement.broker_request)
        self.record_outcome(prepared_placement.broker_name, answer)
        preparation_milliseconds = (answer.sent_at - started_at) * 1000
        return {
            'broker': prepared_placement.broker_name,
            'instrument_id': prepared_placement.instrument_id,
            'tag': prepared_placement.broker_request.tag,
            'outcome': answer.outcome,
            'order_id': answer.order_id,
            'status_message': answer.status_message,
            'broker_response': answer.response_body,
            'skipped': prepared_placement.skipped,
            'timing_ms': {
                'preparation': round(preparation_milliseconds, 3),
                'broker': answer.broker_milliseconds(),
            },
        }, answer.http_status()

    def place(
        self,
        order,
        instrument,
        rotation,
        selector_replies,
        login_texts,
        settings_texts,
        started_at,
    ):
        """Chooses the broker, builds the request and either sends it or answers a dry run.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The instrument the order is for.
            rotation (list): The broker names not excluded by configuration.
            selector_replies (list): The replies to the commands the broker selector queued.
            login_texts (list): Every broker's login as Redis holds it, in `broker_names` order.
            settings_texts (list): Every broker's settings as Redis holds them, in `broker_names` order.
            started_at (float): `time.perf_counter()` when the request arrived.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        prepared_placement = self.prepare(
            order,
            instrument,
            rotation,
            selector_replies,
            login_texts,
            settings_texts,
        )
        if order.dry_run:
            return self.dry_run_answer(prepared_placement, started_at)
        return self.send(prepared_placement, started_at)
