"""Holds a series of requests to a steady rate, and pushes the next one further out after the broker says no.

A `RateLimiter` is the one thing standing between a candle download and a broker's published request limit. Each call to `take` waits, if it has to, until the next request may be sent, and each call to `back_off` pushes that moment further away, which is what the download does for five seconds after a throttle.

This program holds a limiter to twenty requests a second, so consecutive requests are at least fifty milliseconds apart, and backs off by a fifth of a second. The limiter sleeps rather than queueing, so the program measures how long the calls took with a monotonic clock. It prints only whether each wait was at least as long as the limit requires, never the durations themselves, because those differ a little from run to run.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/RateLimiter/example_1_pacing_requests_and_backing_off.py
"""

import time

from stock_brokers.instruments.historical.base import (
    RateLimiter,
)


class PacingRequestsAndBackingOffExample:
    """Takes a few request slots from a limiter and checks how far apart they were.

    Attributes:
        limiter (RateLimiter): The limiter being shown.
    """

    REQUESTS_PER_SECOND = 20.0
    BACK_OFF_SECONDS = 0.2
    TOLERANCE_SECONDS = 0.005

    def __init__(self):
        """Builds a limiter for twenty requests a second with no daily budget.

        Returns:
            None: This method returns nothing.
        """
        self.limiter = RateLimiter(self.REQUESTS_PER_SECOND)

    def run(self):
        """Takes four slots, backs off once, takes one more and prints whether the gaps held.

        Returns:
            None: This method returns nothing.
        """
        minimum_gap = 1.0 / self.REQUESTS_PER_SECOND
        started = time.monotonic()
        for request_number in range(1, 5):
            self.limiter.take()
            print(f'Request {request_number} may be sent')
        four_requests_took = time.monotonic() - started
        print(f'Four requests were held at least three gaps apart: {four_requests_took >= 3 * minimum_gap - self.TOLERANCE_SECONDS}')
        self.limiter.back_off(self.BACK_OFF_SECONDS)
        print(f'The broker said no, so the limiter backs off by {self.BACK_OFF_SECONDS} seconds')
        backed_off_at = time.monotonic()
        self.limiter.take()
        waited = time.monotonic() - backed_off_at
        print('Request 5 may be sent')
        print(f'Request 5 waited at least the back-off: {waited >= self.BACK_OFF_SECONDS - self.TOLERANCE_SECONDS}')


if __name__ == '__main__':
    PacingRequestsAndBackingOffExample().run()
