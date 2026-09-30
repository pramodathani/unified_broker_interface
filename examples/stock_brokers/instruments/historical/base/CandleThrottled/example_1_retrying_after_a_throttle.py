"""Raises `CandleThrottled` when a broker asks for fewer requests, then backs off and retries the same window.

A throttle says something about the pace, not about the instrument, so the right reaction is to wait and ask again for the same window. This program has a stand-in broker that refuses the first request with the message Kite sends when it is asked too often, and a small fetcher that turns that message into `CandleThrottled`. The caller catches it, backs the real `RateLimiter` off by a tenth of a second and asks again, and the second answer comes back with candles.

The stand-in stands for the broker so that nothing leaves the machine. The back-off is kept to a tenth of a second so the program finishes quickly; the candle download itself backs off five seconds.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleThrottled/example_1_retrying_after_a_throttle.py
"""

from stock_brokers.instruments.historical.base import (
    CandleThrottled,
    RateLimiter,
)


class StandInBroker:
    """A stand-in for a broker's history endpoint that refuses its first request.

    Attributes:
        requests (int): How many requests it has received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = 0

    def candles(self, token):
        """Answers a history request, or refuses the first one.

        Args:
            token (str): The instrument token.

        Returns:
            dict: The decoded response.
        """
        self.requests += 1
        if self.requests == 1:
            return {
                'status': 'error',
                'error_type': 'NetworkException',
                'message': 'Too many requests',
            }
        return {
            'status': 'success',
            'candles': [
                [
                    '2026-09-29T00:00:00+0530',
                    1391.0,
                    1402.5,
                    1385.2,
                    1398.4,
                    6123450,
                ],
            ],
            'token': token,
        }


class ThrottleAwareFetcher:
    """Fetches candles and raises `CandleThrottled` when the broker asks for fewer requests.

    Attributes:
        broker (StandInBroker): Where candles come from.
    """

    def __init__(self, broker):
        """Wraps a broker.

        Args:
            broker (StandInBroker): Where candles come from.

        Returns:
            None: This method returns nothing.
        """
        self.broker = broker

    def fetch(self, token):
        """Fetches one window of candles.

        Args:
            token (str): The instrument token.

        Returns:
            list: The candles.

        Raises:
            CandleThrottled: When the broker refuses the request as too frequent.
        """
        answer = self.broker.candles(token)
        if answer['status'] == 'error' and answer['error_type'] == 'NetworkException':
            raise CandleThrottled(answer['message'])
        return answer['candles']


class RetryingAfterAThrottleExample:
    """Fetches one window, backing off and retrying once when throttled.

    Attributes:
        broker (StandInBroker): The stand-in broker.
        fetcher (ThrottleAwareFetcher): The fetcher that raises the throttle.
        limiter (RateLimiter): The pace every request is held to.
    """

    def __init__(self):
        """Builds the broker, the fetcher and a limiter for ten requests a second.

        Returns:
            None: This method returns nothing.
        """
        self.broker = StandInBroker()
        self.fetcher = ThrottleAwareFetcher(self.broker)
        self.limiter = RateLimiter(10.0)

    def run(self):
        """Fetches the window, retrying after a throttle, and prints each step.

        Returns:
            None: This method returns nothing.
        """
        candles = None
        while candles is None:
            self.limiter.take()
            try:
                candles = self.fetcher.fetch('738561')
            except CandleThrottled as error:
                print(f'Throttled: {error}; backing off and asking again for the same window')
                self.limiter.back_off(0.1)
        print(f'Received {len(candles)} candle after {self.broker.requests} requests: {candles[0]}')


if __name__ == '__main__':
    RetryingAfterAThrottleExample().run()
