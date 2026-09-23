"""How many orders a second the engine will send, globally and to any one broker."""

import time


class TokenBucket:
    """A bucket that refills steadily and is emptied one order at a time.

    Attributes:
        capacity (float): The most tokens the bucket holds, which is the largest burst allowed.
        per_second (float): How many tokens a second are added back.
        tokens (float): How many are available now.
        filled_at (float): When the bucket was last refilled, on the monotonic clock.
    """

    def __init__(self, per_second):
        """Builds a full bucket.

        Args:
            per_second (float): How many tokens a second are added back, which is also the capacity.

        Returns:
            None: This method returns nothing.
        """
        self.capacity = per_second
        self.per_second = per_second
        self.tokens = per_second
        self.filled_at = time.monotonic()

    def refill(self, now):
        """Adds the tokens the time since the last refill has earned.

        Args:
            now (float): The moment, on the monotonic clock.

        Returns:
            None: This method returns nothing.
        """
        earned = (now - self.filled_at) * self.per_second
        if earned > 0:
            self.tokens = min(self.capacity, self.tokens + earned)
            self.filled_at = now

    def take(self, now):
        """Takes one token if there is one.

        Args:
            now (float): The moment, on the monotonic clock.

        Returns:
            bool: True when a token was taken.
        """
        self.refill(now)
        if self.tokens >= 1:
            self.tokens = self.tokens - 1
            return True
        return False

    def give_back(self):
        """Puts one token back, for an order that could not be sent after taking it.

        Returns:
            None: This method returns nothing.
        """
        self.tokens = min(self.capacity, self.tokens + 1)

    def wait_for_one(self, now):
        """How long until the next token arrives.

        Args:
            now (float): The moment, on the monotonic clock.

        Returns:
            float: The wait in seconds, zero when a token is available.
        """
        self.refill(now)
        if self.tokens >= 1:
            return 0.0
        if self.per_second <= 0:
            return float('inf')
        return (1 - self.tokens) / self.per_second


class RateBudget:
    """The engine's own limit on how fast it sends orders.

    SEBI's retail algorithmic trading framework, in force since April 2026, treats more than ten orders a second from one account as algorithmic trading needing registration and an exchange algorithm identifier. Brokers apply their own order-to-trade checks on top. The default here is deliberately under that, because the cost of being wrong is a regulatory problem rather than a slow order.

    The budget is held in this process rather than in Redis, and that is correct precisely because `unified:orders:engine:lock` allows exactly one engine to run. Two engines would each keep their own bucket and between them send twice the limit, which is the same reason the lock exists at all.

    **What it does not cover.** The engine sends placements. `PUT /api/orders/modify` and `DELETE /api/orders/cancel` still go straight from an API worker to a broker, and those count against the exchange's limit too. Until they are routed through the engine this is a budget on placements, not on everything the account sends, and it is written here so nobody reads it as more than it is.

    Attributes:
        global_bucket (TokenBucket): The limit across every broker.
        broker_buckets (dict): One bucket per broker, built when that broker is first used.
        per_broker_per_second (float): How many a second any one broker may take.
        wait_seconds (float): The longest an order waits for a token before it is refused.
        logger (logging.Logger): The logger.
        waited (int): How many orders have waited for a token.
        refused (int): How many have been refused because none arrived in time.
    """

    def __init__(self, per_second, per_broker_per_second, wait_seconds, logger):
        """Builds the budget.

        Args:
            per_second (float): Orders a second across every broker.
            per_broker_per_second (float): Orders a second to any one broker.
            wait_seconds (float): The longest an order waits for a token.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.global_bucket = TokenBucket(per_second)
        self.broker_buckets = {}
        self.per_broker_per_second = per_broker_per_second
        self.wait_seconds = wait_seconds
        self.logger = logger
        self.waited = 0
        self.refused = 0

    def broker_bucket(self, broker_name):
        """The bucket for one broker, built the first time that broker is used.

        Args:
            broker_name (str): The broker's name.

        Returns:
            TokenBucket: That broker's bucket.
        """
        bucket = self.broker_buckets.get(broker_name)
        if bucket is None:
            bucket = TokenBucket(self.per_broker_per_second)
            self.broker_buckets[broker_name] = bucket
        return bucket

    def take(self, broker_name, stop=None):
        """Takes one token for a broker, waiting a little for one if the bucket is empty.

        An order waits rather than being refused outright, because a burst arriving within the same tenth of a second is ordinary and a small delay is far better than a refusal the caller has to handle. Only a burst that outlasts the whole wait is refused.

        Both buckets have to give a token or neither is spent, so a broker that has run out does not quietly drain the global budget while it waits for its own.

        Args:
            broker_name (str): The broker the order is going to.
            stop (threading.Event | None): Set when the engine is stopping, so a wait ends early.

        Returns:
            bool: True when the order may be sent.
        """
        deadline = time.monotonic() + self.wait_seconds
        waited = False
        while True:
            if self.take_both(broker_name):
                if waited:
                    self.waited = self.waited + 1
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.refused = self.refused + 1
                self.logger.warning(
                    f'The order rate budget was still empty after '
                    f'{self.wait_seconds} seconds, so an order to '
                    f'{broker_name} was refused rather than sent late.'
                )
                return False
            waited = True
            if self.pause(self.next_token_in(broker_name, remaining), stop):
                self.refused = self.refused + 1
                return False

    def take_both(self, broker_name):
        """Takes a token from the global bucket and the broker's, or from neither.

        Args:
            broker_name (str): The broker the order is going to.

        Returns:
            bool: True when both gave a token.
        """
        now = time.monotonic()
        bucket = self.broker_bucket(broker_name)
        if not self.global_bucket.take(now):
            return False
        if bucket.take(now):
            return True
        self.global_bucket.give_back()
        return False

    def next_token_in(self, broker_name, remaining):
        """How long to wait before trying again.

        Args:
            broker_name (str): The broker the order is going to.
            remaining (float): How much of the wait is left.

        Returns:
            float: The pause in seconds.
        """
        now = time.monotonic()
        longest = max(
            self.global_bucket.wait_for_one(now),
            self.broker_bucket(broker_name).wait_for_one(now),
        )
        return min(remaining, max(0.005, longest))

    def pause(self, seconds, stop):
        """Waits, and says whether the engine was asked to stop instead.

        Args:
            seconds (float): How long to wait.
            stop (threading.Event | None): Set when the engine is stopping.

        Returns:
            bool: True when the engine is stopping and the order should not be sent.
        """
        if stop is None:
            time.sleep(seconds)
            return False
        return bool(stop.wait(seconds))

    def counts(self):
        """What the budget has done, for the engine's shutdown line.

        Returns:
            dict: `waited` and `refused`.
        """
        return {
            'waited': self.waited,
            'refused': self.refused,
        }
