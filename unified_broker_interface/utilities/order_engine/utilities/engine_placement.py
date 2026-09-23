"""Placing one intent's order: the Redis reads the engine makes, and the answer it sends back."""

import json

import redis

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
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
from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)
from unified_broker_interface.utilities.instrument_cache import InstrumentCache

QUOTES_KEY = 'unified:quotes:live'
POSITIONS_KEY = 'unified:portfolio:positions'
ATTRIBUTES_SUFFIX = 'additional_attributes'


class EnginePlacement:
    """Turns one intent into one placed order, reading what it needs from Redis itself.

    This repeats the pipeline ordering `unified_broker_interface/blueprints/orders.py` uses, because the engine builds a broker request of its own and must read the same catalogue entry and credentials. It deliberately does not repeat the instrument lookup: the route resolves the instrument and writes the id into the intent, so the rule that decides an identity is unknown or ambiguous exists once.

    The engine reads two things the route does not have to. Its instrument cache is worth far more here than in a gunicorn worker, because one long-lived process places every order of the day, so most orders cost one Redis round trip rather than two. And it checks no access token, because the route already did.

    Attributes:
        cache (redis.Redis): The Redis client.
        order_placement (OrderPlacement): The half of placement that reads no store.
        instrument_cache (InstrumentCache): The engine's copy of the catalogue entries it has read under the current warm.
        logger (logging.Logger): The logger for failures that do not change an answer.
    """

    def __init__(self, cache, logger):
        """Builds the placement, with one order class and one connection pool per broker.

        Args:
            cache (redis.Redis): The Redis client.
            logger (logging.Logger): The logger for failures that do not change an answer.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the configured broker selector is not a known one.
        """
        self.cache = cache
        self.logger = logger
        self.order_placement = OrderPlacement(logger)
        self.instrument_cache = InstrumentCache()

    def start_connection_warmers(self):
        """Starts the connection warmers configuration names, so an order does not pay for a new handshake.

        Returns:
            None: This method returns nothing.
        """
        self.order_placement.start_connection_warmers()

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Reads the instrument, and the quote and positions a reference needs, in one round trip.

        This is a separate read from `prepare`'s, and deliberately queues none of the broker selector's commands. The selector's `round_robin` counts an `INCR` for every order it is asked about, so reading through `prepare` twice would advance the rotation twice and quietly skip a broker on every referenced order.

        The instrument comes from the engine's own cache when it holds one, so after the first order of the day on an instrument this costs only the quote and the positions.

        Args:
            instrument_id (str): The instrument the order is for.
            needs_quote (bool): Whether a price reference needs the live quote.
            needs_positions (bool): Whether a quantity reference needs the positions.

        Returns:
            tuple: The instrument (Instrument), the quote (dict | None) and the positions (dict | None).

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read or nothing has been mapped, and 404 when the instrument is not mapped.
        """
        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.get('unified:catalogue:current_date')
            pipeline.get('unified:catalogue:warm_identifier')
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'Redis could not be read: {error}',
                503,
            )
        mapping_date_text, warm_identifier = replies[0], replies[1]
        if not mapping_date_text:
            raise RefusedRequestError.refusal(
                'no instruments have been mapped yet',
                503,
            )

        catalogue_key_prefix = f'unified:catalogue:{mapping_date_text}:'
        kept_texts = self.instrument_cache.instrument(
            mapping_date_text,
            warm_identifier,
            instrument_id,
        )
        pipeline = self.cache.pipeline(transaction=False)
        if kept_texts is None:
            pipeline.hget(catalogue_key_prefix + 'identity', instrument_id)
            pipeline.hget(
                catalogue_key_prefix + 'order_handles',
                instrument_id,
            )
            pipeline.hget(
                catalogue_key_prefix + 'contract_sizes',
                instrument_id,
            )
        if needs_quote:
            pipeline.hget(QUOTES_KEY, instrument_id)
        if needs_positions:
            pipeline.get(POSITIONS_KEY)
        try:
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'Redis could not be read: {error}',
                503,
            )

        position = 0
        if kept_texts is None:
            identity_text, handles_text, contract_size_text = replies[0:3]
            position = 3
        else:
            identity_text, handles_text, contract_size_text = kept_texts
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
        quote = None
        if needs_quote:
            quote = self.decode(replies[position])
            position = position + 1
        positions = None
        if needs_positions:
            positions = self.decode(replies[position])
        return instrument, quote, positions

    def read_credentials_for(self, broker_name):
        """One broker's login and settings, and the order book entry reader they go with.

        Args:
            broker_name (str): The broker.

        Returns:
            tuple: The broker's order class (BrokerOrders), its login (object) and its settings (dict).

        Raises:
            RefusedRequestError: With HTTP 503 when the broker is not one this engine knows or Redis cannot be read.
        """
        broker_orders = self.order_placement.broker_orders.get(broker_name)
        if broker_orders is None:
            raise RefusedRequestError.refusal(
                f'{broker_name} is not a broker this engine places orders at',
                503,
                broker=broker_name,
            )
        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.hget('last_login', broker_name)
            pipeline.hget('settings', broker_name)
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'Redis could not be read: {error}',
                503,
                broker=broker_name,
            )
        return (
            broker_orders,
            broker_orders.decode_login(replies[0]),
            broker_orders.decode_settings(replies[1]),
        )

    def stored_order(self, broker_name, broker_order_id):
        """One order as the broker's own order book in Redis holds it.

        A cancel or a modification cannot be built from what the engine remembers sending. Several brokers need values only their order book carries — Zerodha's `variety`, Kotak's after-market flag, Wisdom Capital's unique identifier — and `docs/contributing/pitfalls.md` records each of them as a live failure found the hard way.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's own order id.

        Returns:
            StoredOrder: The stored order.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read, and 404 when the broker's order book does not hold the order yet.
        """
        try:
            stored = self.cache.hget(
                f'{broker_name}:orders:orders',
                str(broker_order_id),
            )
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'Redis could not be read: {error}',
                503,
                broker=broker_name,
            )
        entry = self.decode(stored)
        if entry is None:
            raise RefusedRequestError.refusal(
                f"{broker_name}'s order book does not hold {broker_order_id} "
                'yet, so it cannot be changed',
                404,
                broker=broker_name,
                order_id=str(broker_order_id),
            )
        return StoredOrder(entry)

    def cancel(self, broker_name, broker_order_id):
        """Cancels one order at a broker.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's own order id.

        Returns:
            BrokerAnswer: What the broker said.

        Raises:
            RefusedRequestError: With HTTP 503 when the order cannot be read or the broker cannot take a cancel, and 404 when the order book does not hold it.
        """
        broker_orders, login, settings = self.read_credentials_for(broker_name)
        problem = broker_orders.cancel_problem(login, settings)
        if problem is not None:
            raise RefusedRequestError.refusal(
                problem,
                503,
                broker=broker_name,
            )
        stored = self.stored_order(broker_name, broker_order_id)
        broker_request = broker_orders.build_cancel_request(
            str(broker_order_id),
            stored,
            login,
            settings,
        )
        return broker_orders.send_cancel(broker_request)

    def modify_leg(
        self,
        broker_name,
        broker_order_id,
        quantity=None,
        price=None,
        trigger_price=None,
    ):
        """Changes one order at a broker, leaving whatever is not named as it was.

        Changing the quantity is what reduces the other leg of a linked pair when one of them partly fills, which the Atlas names as the correct way to run an OCO rather than cancelling and replacing. Changing a price is what moves a stop to breakeven after a first target fills, and what every type that re-prices a resting order will do.

        Quantities are in the broker's own terms, as the order book stores them and as a leg records them, so nothing is converted here.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's own order id.
            quantity (int | None): The new quantity, in the broker's own terms, or None to leave it.
            price (decimal.Decimal | float | None): The new limit price, or None to leave it.
            trigger_price (decimal.Decimal | float | None): The new trigger price, or None to leave it.

        Returns:
            BrokerAnswer: What the broker said.

        Raises:
            RefusedRequestError: With HTTP 400 when nothing was named to change, 501 when the broker takes no modifications, 503 when the order cannot be read, and 404 when the order book does not hold it.
        """
        if quantity is None and price is None and trigger_price is None:
            raise RefusedRequestError.refusal(
                'a modification has to change something',
                400,
                broker=broker_name,
            )
        broker_orders, login, settings = self.read_credentials_for(broker_name)
        if not broker_orders.takes_modifications():
            raise RefusedRequestError.refusal(
                f'{broker_name} does not take modifications through its API',
                501,
                broker=broker_name,
            )
        problem = broker_orders.modify_problem(login, settings)
        if problem is not None:
            raise RefusedRequestError.refusal(
                problem,
                503,
                broker=broker_name,
            )
        stored = self.stored_order(broker_name, broker_order_id)
        changes = {
            'order_id': str(broker_order_id),
        }
        if quantity is not None:
            changes['quantity'] = quantity
        if price is not None:
            changes['price'] = str(price)
        if trigger_price is not None:
            changes['trigger_price'] = str(trigger_price)
        modify_request = ModifyOrderRequest(
            changes,
            {},
            self.order_placement.broker_names,
        )
        # OrderModification holds the stored order with the request's changes laid over it, and it
        # deliberately keeps the STORED quantity: the blueprint's modify route converts a caller's
        # units into the broker's terms and only then calls with_quantities. The engine's quantity
        # is already in the broker's terms, so there is nothing to convert, but the call still has
        # to be made. Leaving it out sent the stored quantity while the engine recorded the new one,
        # so the engine believed a leg had been reduced while the broker still had it whole.
        modification = OrderModification(modify_request, stored)
        if quantity is not None:
            modification = modification.with_quantities(
                quantity,
                min(modification.disclosed_quantity or 0, quantity),
            )
        broker_request = broker_orders.build_modify_request(
            str(broker_order_id),
            stored,
            modification,
            login,
            settings,
        )
        return broker_orders.send_modify(broker_request)

    def broker_attributes(self, instrument_id):
        """Every broker's extra fields for one instrument, such as the exchange freeze quantity.

        These live in a hash of their own rather than in the order handle, which carries only the broker token, the order symbol, the lot size and the tick size. Only five of the ten brokers publish a freeze quantity at all, so the answer is often partly empty and a caller has to cope with that rather than assume.

        Args:
            instrument_id (str): The instrument.

        Returns:
            dict: Broker names to their attributes, which may be empty.
        """
        try:
            mapping_date_text = self.cache.get(
                'unified:catalogue:current_date',
            )
            if not mapping_date_text:
                return {}
            stored = self.cache.hget(
                f'unified:catalogue:{mapping_date_text}:{ATTRIBUTES_SUFFIX}',
                instrument_id,
            )
        except redis.RedisError as error:
            self.logger.warning(
                f"the extra attributes for {instrument_id} could not be read "
                f'({error}), so anything that needs them will do without.'
            )
            return {}
        document = self.decode(stored)
        return document or {}

    def decode(self, text):
        """One JSON document from Redis, or None when there is none or it is not an object.

        Args:
            text (str | None): The stored document.

        Returns:
            dict | None: The decoded document.
        """
        if not text:
            return None
        try:
            document = json.loads(text)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        return document

    def prepare(self, order, instrument_id, broker_name=None):
        """Reads what the order needs, chooses its broker and builds the request, without sending anything.

        The seam between building and sending is where a synthetic order records that it is about to send, so that a crash mid-send leaves evidence of an order that may exist.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument the intent named.
            broker_name (str | None): The broker the order must go to, or None to let the selector choose.

        Returns:
            PreparedPlacement: The chosen broker and the request built for it.

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        if not instrument_id:
            raise RefusedRequestError.refusal(
                'the intent names no instrument, so the order cannot be placed',
                503,
            )

        rotation = self.order_placement.rotation()
        mapping_date_text, warm_identifier, login_texts, settings_texts = (
            self.read_credentials()
        )
        if not mapping_date_text:
            raise RefusedRequestError.refusal(
                'no instruments have been mapped yet',
                503,
            )

        instrument, selector_replies = self.read_instrument(
            order,
            instrument_id,
            mapping_date_text,
            warm_identifier,
        )
        return self.order_placement.prepare(
            order,
            instrument,
            rotation,
            selector_replies,
            login_texts,
            settings_texts,
            broker_name,
        )

    def send(self, prepared_placement, started_at):
        """Sends a prepared order to its broker and reads the answer.

        Args:
            prepared_placement (PreparedPlacement): The chosen broker and its built request.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        return self.order_placement.send(prepared_placement, started_at)

    def dry_run_answer(self, prepared_placement, started_at):
        """Answers with the request that would have been sent, without sending it.

        Args:
            prepared_placement (PreparedPlacement): The chosen broker and its built request.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        return self.order_placement.dry_run_answer(
            prepared_placement,
            started_at,
        )

    def read_order(self, intent):
        """Rebuilds the validated order from the caller's body, exactly as the route built it.

        Args:
            intent (dict): The intent document.

        Returns:
            PlaceOrderRequest: The validated order.

        Raises:
            RefusedRequestError: With HTTP 400 when the body does not validate, which means the route and the engine disagree and is worth answering rather than hiding.
        """
        try:
            return PlaceOrderRequest(intent.get('body'))
        except InvalidOrderError as error:
            raise RefusedRequestError.refusal(str(error), 400)

    def read_credentials(self):
        """Reads the mapping marker and every broker's login and settings in one round trip.

        Returns:
            tuple: The mapping date (str | None), the warm identifier (str | None), the logins (list) and the settings (list), the last two in `broker_names` order.

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read.
        """
        broker_names = self.order_placement.broker_names
        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.get('unified:catalogue:current_date')
            pipeline.get('unified:catalogue:warm_identifier')
            pipeline.hmget('last_login', broker_names)
            pipeline.hmget('settings', broker_names)
            replies = pipeline.execute()
        except redis.RedisError as error:
            raise RefusedRequestError.refusal(
                f'Redis could not be read: {error}',
                503,
            )
        return replies[0], replies[1], replies[2], replies[3]

    def read_instrument(
        self,
        order,
        instrument_id,
        mapping_date_text,
        warm_identifier,
    ):
        """Reads the instrument's catalogue entry and the broker selector's own commands in one round trip.

        The entry is read from the engine's cache when it holds one for the current warm, and the round trip is skipped entirely when the selector queues nothing either, which is what `fixed_priority` does.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument the intent named.
            mapping_date_text (str): The mapping date as Redis holds it.
            warm_identifier (str | None): The current warm's identifier.

        Returns:
            tuple: The instrument (Instrument) and the selector's replies (list).

        Raises:
            RefusedRequestError: With HTTP 503 when Redis cannot be read, and 404 when the instrument is not mapped.
        """
        catalogue_key_prefix = f'unified:catalogue:{mapping_date_text}:'
        kept_texts = self.instrument_cache.instrument(
            mapping_date_text,
            warm_identifier,
            instrument_id,
        )
        pipeline = self.cache.pipeline(transaction=False)
        if kept_texts is None:
            pipeline.hget(catalogue_key_prefix + 'identity', instrument_id)
            pipeline.hget(
                catalogue_key_prefix + 'order_handles',
                instrument_id,
            )
            pipeline.hget(
                catalogue_key_prefix + 'contract_sizes',
                instrument_id,
            )
        selector_command_count = (
            self.order_placement.broker_selector.queue_redis_commands(
                pipeline,
                order,
                instrument_id,
            )
        )
        replies = []
        if kept_texts is None or selector_command_count > 0:
            try:
                replies = pipeline.execute()
            except redis.RedisError as error:
                raise RefusedRequestError.refusal(
                    f'Redis could not be read: {error}',
                    503,
                )
        if kept_texts is None:
            identity_text = replies[0]
            handles_text = replies[1]
            contract_size_text = replies[2]
            selector_replies = replies[3:]
        else:
            identity_text = kept_texts[0]
            handles_text = kept_texts[1]
            contract_size_text = kept_texts[2]
            selector_replies = replies

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
        return instrument, selector_replies
