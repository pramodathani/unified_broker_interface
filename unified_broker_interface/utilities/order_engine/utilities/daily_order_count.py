"""Counting every order message sent to each broker in a day, and refusing new ones before a broker's daily cap is reached."""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
    RESET_HOUR,
)
from utilities.configurations import api_configuration

COUNT_KEY_PREFIX = 'unified:orders:daily_count:'


class DailyOrderCount:
    """How many order messages each capped broker has been sent today, against the cap that broker allows.

    Some brokers refuse every order message past a fixed number a day, and a message is a placement, a modification or a cancellation alike. Zerodha counts rejected orders too, and once its cap is reached it refuses even the order that would close a position. So the count stops new entries a little before the cap, and keeps the rest of the cap for exits.

    Counting happens in `BrokerOrders.send`, which every placement, modification and cancellation passes through, whether the order engine or a REST API worker sent it, so a message cannot reach a capped broker without being counted. A request that could not connect is not counted, because it never left; one the broker answered with a refusal is. The count lives in Redis, one key per broker, and expires at the next 06:00 IST, so it is shared between processes, survives a restart and starts again every trading day.

    Only brokers with a configured cap are counted, so an order to any other broker costs no Redis call. A broker with no configured cap is never refused. A count that cannot be read does not refuse either, for the same reason the loss lockout does not: Redis being unreadable for a moment should not become an outage of its own. The failure is logged.

    Attributes:
        cache (redis.Redis): The Redis client.
        caps (dict): Each capped broker's daily cap (int), by broker name.
        exit_reserve (float): The share of each cap kept back for orders that close a position, between 0 and 1.
        logger (logging.Logger): The logger.
        refused (int): How many orders have been refused.
    """

    def __init__(self, cache, caps, exit_reserve, logger):
        """Builds the count.

        Args:
            cache (redis.Redis): The Redis client.
            caps (dict): Each capped broker's daily cap (int), by broker name.
            exit_reserve (float): The share of each cap kept back for exits, between 0 and 1.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the exit reserve is outside 0 to 1, or a cap is not above zero.
        """
        if exit_reserve < 0 or exit_reserve >= 1:
            raise ValueError(f'The exit reserve must be from 0 up to 1: {exit_reserve=}')
        for broker_name, cap in caps.items():
            if cap <= 0:
                raise ValueError(f'A daily order cap must be above zero: {broker_name=} {cap=}')
        self.cache = cache
        self.caps = caps
        self.exit_reserve = exit_reserve
        self.logger = logger
        self.refused = 0

    @classmethod
    def from_configuration(cls, cache, logger):
        """Builds the count from the configured caps, or returns None when no broker is capped.

        Args:
            cache (redis.Redis): The Redis client.
            logger (logging.Logger): The logger.

        Returns:
            DailyOrderCount | None: The count.

        Raises:
            ValueError: When the configured caps or exit reserve cannot be read.
        """
        caps = cls.read_caps(api_configuration['order_daily_caps'])
        if not caps:
            return None
        return cls(
            cache,
            caps,
            api_configuration['order_daily_cap_exit_reserve'],
            logger,
        )

    @staticmethod
    def read_caps(text):
        """Reads the caps out of the configuration's `broker=cap,broker=cap` text.

        Args:
            text (str): The configured text, which may be empty.

        Returns:
            dict: Each broker's daily cap (int), by broker name.

        Raises:
            ValueError: When an entry is not `broker=whole number`.
        """
        caps = {}
        for entry in text.replace(' ', '').lower().split(','):
            if not entry:
                continue
            broker_name, separator, number = entry.partition('=')
            if not separator or not broker_name or not number.isdigit():
                raise ValueError(f'A daily order cap must read broker=number: {entry=}')
            caps[broker_name] = int(number)
        return caps

    def key(self, broker_name):
        """The Redis key holding one broker's count.

        Args:
            broker_name (str): The broker.

        Returns:
            str: The key.
        """
        return f'{COUNT_KEY_PREFIX}{broker_name}'

    def next_reset(self, now=None):
        """The next 06:00 IST, when every count expires.

        Args:
            now (datetime.datetime | None): The moment to reckon from, or None for now in IST.

        Returns:
            int: The moment as an epoch in seconds.
        """
        now = now or datetime.datetime.now(INDIA)
        reset = now.replace(
            hour=RESET_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
        if reset <= now:
            reset = reset + datetime.timedelta(days=1)
        return int(reset.timestamp())

    def entry_limit(self, cap):
        """How many orders a broker may be sent before new entries are refused.

        Args:
            cap (int): The broker's daily cap.

        Returns:
            int: The count at which entries stop.
        """
        return cap - int(cap * self.exit_reserve)

    def sent_today(self, broker_name):
        """How many order messages a broker has been sent today, or None when the count cannot be read.

        Args:
            broker_name (str): The broker.

        Returns:
            int | None: The count.
        """
        try:
            stored = self.cache.get(self.key(broker_name))
        except Exception as error:
            self.logger.warning(
                f'The daily order count for {broker_name} could not be read '
                f'({error}), so its cap is not being applied to this order.'
            )
            return None
        if stored is None:
            return 0
        try:
            return int(stored)
        except (TypeError, ValueError):
            return None

    def refuse_if_capped(self, broker_name, closes_position):
        """Refuses one order when its broker is too close to the day's cap.

        Args:
            broker_name (str): The broker the order would go to.
            closes_position (bool): Whether the message is about a position being closed, which may use the exit reserve.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 429 when the broker has no room left for this kind of order.
        """
        cap = self.caps.get(broker_name)
        if cap is None:
            return
        sent = self.sent_today(broker_name)
        if sent is None:
            return
        limit = cap if closes_position else self.entry_limit(cap)
        if sent < limit:
            return
        self.refused = self.refused + 1
        if closes_position:
            reason = (
                f'{broker_name} has been sent {sent} order messages today, '
                f'which is its daily cap of {cap}, so this was not sent'
            )
        else:
            reason = (
                f'{broker_name} has been sent {sent} order messages today, '
                f'and the last {cap - limit} of its daily cap of {cap} are '
                'kept for closing positions, so this was not sent'
            )
        raise RefusedRequestError.refusal(
            reason,
            429,
            broker=broker_name,
        )

    def count_sent(self, broker_name):
        """Counts one order message sent to a broker, when that broker is capped.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        if broker_name not in self.caps:
            return
        key = self.key(broker_name)
        try:
            pipeline = self.cache.pipeline(transaction=False)
            pipeline.incr(key)
            pipeline.expireat(key, self.next_reset())
            pipeline.execute()
        except Exception as error:
            self.logger.warning(
                f'The daily order count for {broker_name} could not be '
                f'written ({error}), so today\'s count is now short by one.'
            )

    def counts(self):
        """What the count has done, for the engine's shutdown line.

        Returns:
            dict: `refused`, and `caps` as configured.
        """
        return {
            'refused': self.refused,
            'caps': dict(self.caps),
        }
