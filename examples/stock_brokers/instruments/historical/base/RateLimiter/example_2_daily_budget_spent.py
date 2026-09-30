"""Refuses a request once a broker's daily budget is spent, by raising `CandleThrottled`.

Some brokers publish a daily cap on historical requests as well as a rate. A `RateLimiter` given `requests_per_day` counts every slot `take` hands out, and once the day's budget is used up it raises `CandleThrottled` instead of waiting. The candle download treats that as a reason to stop for the day rather than to retry, because waiting a few seconds would not help.

This program uses a budget of three requests and a rate of a hundred a second, so it finishes in a few hundredths of a second. The budget resets when the date changes, which the program does not wait for.

What to notice in the output: the first three requests are allowed, the fourth raises `CandleThrottled` with a message naming the budget, and a fifth attempt is refused the same way, because nothing about the budget changed.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/RateLimiter/example_2_daily_budget_spent.py
"""

from stock_brokers.instruments.historical.base import (
    CandleThrottled,
    RateLimiter,
)


class DailyBudgetSpentExample:
    """Takes request slots until the daily budget refuses one.

    Attributes:
        limiter (RateLimiter): The limiter being shown.
    """

    def __init__(self):
        """Builds a limiter for a hundred requests a second and three a day.

        Returns:
            None: This method returns nothing.
        """
        self.limiter = RateLimiter(100.0, requests_per_day=3)

    def run(self):
        """Asks for five requests and prints which were allowed.

        Returns:
            None: This method returns nothing.
        """
        for request_number in range(1, 6):
            try:
                self.limiter.take()
            except CandleThrottled as error:
                print(f'Request {request_number} refused: {error}')
                continue
            print(f'Request {request_number} allowed')


if __name__ == '__main__':
    DailyBudgetSpentExample().run()
