"""Keeps the daily budget in Redis, so a downloader that restarts carries on counting from where the last one stopped.

A candle downloader exits when its daily budget is spent, and systemd starts it again ten minutes later. A count kept only in the process would begin again at zero each time, so the cap would never hold. Given a Redis client and a key, a `RateLimiter` counts every request in `<key>:<date in India>` instead, which `spent_today` reads back and which expires after two days. This program uses a small stand-in for Redis, so it needs nothing running.

`set_requests_per_day` changes the cap while running, which the Fyers downloader uses to raise its cap at weekends; the count carries on either way.

Notice that the second limiter, standing in for the restarted process, starts at 2 rather than 0 and refuses its second request.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/RateLimiter/example_3_budget_kept_in_redis.py
"""

from stock_brokers.instruments.historical.base import (
    CandleThrottled,
    RateLimiter,
)


class StandInPipeline:
    """A pipeline that applies `INCR` to a stand-in Redis when executed.

    Attributes:
        cache (StandInRedis): The stand-in Redis.
        keys (list): The keys to increment.
    """

    def __init__(self, cache):
        """Builds the pipeline.

        Args:
            cache (StandInRedis): The stand-in Redis.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.keys = []

    def incr(self, key):
        """Queues an `INCR`.

        Args:
            key (str): The key.

        Returns:
            StandInPipeline: This pipeline.
        """
        self.keys.append(key)
        return self

    def expire(self, key, seconds):
        """Accepts an `EXPIRE`, which the stand-in does not act on.

        Args:
            key (str): The key.
            seconds (int): The time to live.

        Returns:
            StandInPipeline: This pipeline.
        """
        del key
        del seconds
        return self

    def execute(self):
        """Applies the queued increments.

        Returns:
            None: This method returns nothing.
        """
        for key in self.keys:
            self.cache.values[key] = str(int(self.cache.values.get(key, '0')) + 1)


class StandInRedis:
    """A Redis holding string values in a dictionary.

    Attributes:
        values (dict): The keys and their values.
    """

    def __init__(self):
        """Builds an empty Redis.

        Returns:
            None: This method returns nothing.
        """
        self.values = {}

    def get(self, key):
        """Reads a value.

        Args:
            key (str): The key.

        Returns:
            str | None: The value.
        """
        return self.values.get(key)

    def pipeline(self, transaction=True):
        """A pipeline.

        Args:
            transaction (bool): Ignored.

        Returns:
            StandInPipeline: The pipeline.
        """
        del transaction
        return StandInPipeline(self)


class BudgetKeptInRedisExample:
    """Spends a budget of three across two limiters that share a stand-in Redis.

    Attributes:
        cache (StandInRedis): The shared stand-in Redis.
    """

    def __init__(self):
        """Builds the stand-in Redis.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()

    def run(self):
        """Takes two requests, restarts, and takes two more.

        Returns:
            None: This method returns nothing.
        """
        first = RateLimiter(1000.0, 3, self.cache, 'fyers:price_history:requests')
        first.take()
        first.take()
        print(f'First process spent {first.spent_today()} requests')
        second = RateLimiter(1000.0, 3, self.cache, 'fyers:price_history:requests')
        print(f'Restarted process starts at {second.spent_today()}')
        second.take()
        try:
            second.take()
        except CandleThrottled as error:
            print(f'Its second request: {error}')
        second.set_requests_per_day(None)
        second.take()
        print(f'With the cap lifted, one more is allowed; spent today: {second.spent_today()}')
        key = f'fyers:price_history:requests:{second.budget_date().isoformat()}'
        print(f'Redis holds {self.cache.get(key)} under the key for today')


if __name__ == '__main__':
    BudgetKeptInRedisExample().run()
