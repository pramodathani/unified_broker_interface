"""Shows `CandleThrottled` raised by a `RateLimiter` whose daily budget is spent, and the loop stopping for the day.

`CandleThrottled` has two sources. A broker raises it through `fetch_candles` when it is asked too often, and the `RateLimiter` raises it itself when a broker's daily request budget is used up. The second kind will not clear by waiting a few seconds, so the candle download's `run` stops when it meets it and leaves the rest of the queue for tomorrow.

This program runs a small loop over five series with a budget of two requests a day. No broker is contacted: each "request" only prints the series it would have fetched. It also shows that `CandleThrottled` is a `CandleError`.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleThrottled/example_2_budget_spent_for_the_day.py
"""

from stock_brokers.instruments.historical.base import (
    CandleError,
    CandleThrottled,
    RateLimiter,
)


class BudgetSpentForTheDayExample:
    """Works through a queue until the daily budget stops it.

    Attributes:
        limiter (RateLimiter): The limiter with a two-request daily budget.
        queue (list): The series tokens waiting to be fetched.
    """

    def __init__(self):
        """Builds the limiter and the queue.

        Returns:
            None: This method returns nothing.
        """
        self.limiter = RateLimiter(100.0, requests_per_day=2)
        self.queue = [
            '738561',
            '2953217',
            '408065',
            '884737',
            '341249',
        ]

    def run(self):
        """Fetches series until the budget is spent, then prints what is left.

        Returns:
            None: This method returns nothing.
        """
        fetched = []
        for token in self.queue:
            try:
                self.limiter.take()
            except CandleThrottled as error:
                print(f'Stopping for the day: {error}')
                print(f'It is a CandleError: {isinstance(error, CandleError)}')
                break
            print(f'Fetching {token}')
            fetched.append(token)
        left = []
        for token in self.queue:
            if token not in fetched:
                left.append(token)
        print(f'Left for tomorrow: {left}')


if __name__ == '__main__':
    BudgetSpentForTheDayExample().run()
