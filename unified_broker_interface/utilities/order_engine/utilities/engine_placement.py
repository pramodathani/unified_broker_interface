"""Placing one intent's order: the Redis reads the engine makes, and the answer it sends back."""

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
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.instrument_cache import InstrumentCache


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

    def place(self, intent):
        """Places the order one intent describes and builds the answer for the waiting API worker.

        Args:
            intent (dict): The intent document read off the stream.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.read_order(intent)
        instrument_id = intent.get('instrument_id')
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
        return self.order_placement.place(
            order,
            instrument,
            rotation,
            selector_replies,
            login_texts,
            settings_texts,
            intent['engine_started_at'],
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
