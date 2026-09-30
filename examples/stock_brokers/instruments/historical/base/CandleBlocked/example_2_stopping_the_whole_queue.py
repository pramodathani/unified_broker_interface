"""Stops a whole queue of series on `CandleBlocked`, where a throttle only costs the one series a pause.

Moving on to the next series after a ban is simply another request to a firewall that is counting them. This program works a queue of five series against a stand-in broker that throttles the second series and bans the client on the fourth. The loop carries on past the throttle and stops at the ban, leaving the fifth series untouched, which is how the candle download's `run` treats the two failures.

The stand-in broker answers from a script, so no request leaves the machine.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleBlocked/example_2_stopping_the_whole_queue.py
"""

from stock_brokers.instruments.historical.base import (
    CandleBlocked,
    CandleThrottled,
)


class StandInBroker:
    """A stand-in broker that answers each token from a script.

    Attributes:
        requests (list): The tokens asked for, in order.
    """

    def __init__(self):
        """Builds the broker with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def fetch(self, token):
        """Fetches one window of candles for a token.

        Args:
            token (str): The instrument token.

        Returns:
            int: How many candles came back.

        Raises:
            CandleThrottled: For the token scripted to be throttled.
            CandleBlocked: For the token scripted to meet the ban.
        """
        self.requests.append(token)
        if token == 'NSE:SBIN-EQ':
            raise CandleThrottled('request limit reached')
        if token == 'NSE:INFY-EQ':
            raise CandleBlocked('error code: 1015')
        return 75


class StoppingTheWholeQueueExample:
    """Works a queue until a ban stops it.

    Attributes:
        broker (StandInBroker): The stand-in broker.
        queue (list): The series to fetch.
    """

    def __init__(self):
        """Builds the broker and the queue.

        Returns:
            None: This method returns nothing.
        """
        self.broker = StandInBroker()
        self.queue = [
            'NSE:RELIANCE-EQ',
            'NSE:SBIN-EQ',
            'NSE:TCS-EQ',
            'NSE:INFY-EQ',
            'NSE:HDFCBANK-EQ',
        ]

    def run(self):
        """Works the queue and prints each series' outcome.

        Returns:
            None: This method returns nothing.
        """
        for token in self.queue:
            try:
                candles = self.broker.fetch(token)
            except CandleThrottled as error:
                print(f'{token}: throttled ({error}), left claimable for later')
                continue
            except CandleBlocked as error:
                print(f'{token}: blocked ({error}), stopping the broker')
                break
            print(f'{token}: {candles} candles stored')
        print(f'Requests sent: {len(self.broker.requests)} of {len(self.queue)}')


if __name__ == '__main__':
    StoppingTheWholeQueueExample().run()
