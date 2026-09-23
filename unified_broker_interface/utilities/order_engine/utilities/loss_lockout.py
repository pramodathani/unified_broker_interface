"""Refusing new orders once the day has lost more than it was allowed to."""

import json

FUNDS_KEY = 'unified:portfolio:funds'


class LossLockout:
    """A gate in front of every order, driven by the day's profit and loss.

    This is the gate that matters most and is the cheapest to get wrong. A strategy that is losing steadily will keep placing orders until something stops it, and the thing that stops it should not be somebody noticing.

    It reads `unified:portfolio:funds`, which `bin/unified/portfolio/funds` rewrites every half second across every broker, and adds realized to unrealized. Unrealized is included deliberately: a position held at a large loss has lost the money whether or not it has been closed, and a lockout that ignored it would let a strategy average down indefinitely.

    It is off unless a limit is configured, because a limit guessed on somebody's behalf is worse than none: too low it stops a normal day, too high it is theatre. The number belongs to whoever is trading.

    A funds document that cannot be read does **not** lock trading out. That direction was chosen deliberately: Redis being briefly unreadable is common, and a gate that turned every such moment into a halt would be its own outage. The failure is logged so it is visible.

    Attributes:
        cache (redis.Redis): The Redis client.
        limit (float): The most the day may lose before new orders are refused; zero or less turns the gate off.
        logger (logging.Logger): The logger.
        locked_out (int): How many orders have been refused.
    """

    def __init__(self, cache, limit, logger):
        """Builds the lockout.

        Args:
            cache (redis.Redis): The Redis client.
            limit (float): The most the day may lose, as a positive number; zero or less turns the gate off.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.limit = limit
        self.logger = logger
        self.locked_out = 0

    def is_configured(self):
        """Whether a limit was set at all.

        Returns:
            bool: True when the gate is on.
        """
        return self.limit > 0

    def day_profit(self):
        """The day's profit and loss across every broker, or None when it cannot be read.

        Returns:
            float | None: Realized plus unrealized, negative for a loss.
        """
        try:
            stored = self.cache.get(FUNDS_KEY)
        except Exception as error:
            self.logger.warning(
                f'{FUNDS_KEY} could not be read ({error}), so the daily loss '
                'lockout is not being applied to this order.'
            )
            return None
        if not stored:
            return None
        try:
            document = json.loads(stored)
        except ValueError:
            return None
        profit_and_loss = document.get('pnl')
        if not isinstance(profit_and_loss, dict):
            return None
        total = 0.0
        for name in ('realized', 'unrealized'):
            value = profit_and_loss.get(name)
            if isinstance(value, (int, float)):
                total = total + float(value)
        return total

    def refusal_reason(self):
        """Why a new order should be refused, or None when it should not.

        Returns:
            str | None: The reason, for the caller to answer with.
        """
        if not self.is_configured():
            return None
        profit = self.day_profit()
        if profit is None:
            return None
        if profit > -self.limit:
            return None
        self.locked_out = self.locked_out + 1
        return (
            f'the day is down {abs(profit):.2f}, which is past the '
            f'{self.limit:.2f} limit, so no new order is being placed'
        )
