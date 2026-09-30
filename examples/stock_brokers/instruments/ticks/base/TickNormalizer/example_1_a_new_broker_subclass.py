"""Writes the normalizer for a new broker by subclassing `TickNormalizer`, and asks it the questions the resolver asks.

A broker's normalizer states facts about that broker and leaves the work to the base class. It implements `feed_key`, which turns the token on a tick into the broker token and canonical segments the mappings are searched with, and sets class attributes that say which quantities arrive in lots, when `close` is the previous close and which timestamps are true instants. The subclass here is for an imaginary broker whose feed spells tokens `NSE-2885` and `MCX-440001`, reports MCX volume and open interest in lots, and trusts its close on NSE only.

The program then calls the base class's own methods on it: `quantity_basis` and `close_policy`, which the resolver asks when it compiles a plan, and `tick_spelling`, whose default keeps a subscription token as it is. Everything is pure computation, so no data store or broker is involved.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/base/TickNormalizer/example_1_a_new_broker_subclass.py
"""

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    TickNormalizer,
)


class ImaginaryBrokerTickNormalizer(TickNormalizer):
    """Normalizes ticks from an imaginary broker whose tokens are spelled `EXCHANGE-TOKEN`."""

    BROKER_NAME = 'imaginary'
    FAMILIES = {
        'NSE': 'cash_or_index',
        'NFO': 'derivative',
        'MCX': 'derivative',
    }
    EXCHANGES = {
        'NSE': 'nse',
        'NFO': 'nse',
        'MCX': 'mcx',
    }
    LOT_FIELDS = {
        'mcx': frozenset(
            [
                'volume',
                'oi',
            ]
        ),
    }
    CLOSE_POLICY = {
        'nse': base.CLOSE_ALWAYS,
    }
    TRUSTS_EXCHANGE_TIME = False

    def feed_key(self, instrument_token):
        """Reads the broker token and segments out of an `EXCHANGE-TOKEN` token.

        Args:
            instrument_token (str): The tick's token, such as `NSE-2885`.

        Returns:
            FeedKey | None: The key, or None for a token this normalizer cannot place.
        """
        exchange, _, token = str(instrument_token).partition('-')
        if exchange not in self.FAMILIES or not token:
            return None
        segments = base.family_segments(
            [
                self.EXCHANGES[exchange],
            ],
            self.FAMILIES[exchange],
        )
        return base.FeedKey(token, segments)


class NewBrokerSubclassExample:
    """Asks the imaginary broker's normalizer everything the resolver asks.

    Attributes:
        normalizer (ImaginaryBrokerTickNormalizer): The normalizer being shown.
    """

    def __init__(self):
        """Builds the normalizer.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = ImaginaryBrokerTickNormalizer()

    def run(self):
        """Prints feed keys, tick spellings, quantity bases and close policies.

        Returns:
            None: This method returns nothing.
        """
        tokens = [
            'NSE-2885',
            'MCX-440001',
            'LSE-1',
        ]
        for token in tokens:
            feed_key = self.normalizer.feed_key(token)
            if feed_key is None:
                print(f'{token}: cannot be placed')
                continue
            print(f'{token}: broker token {feed_key.broker_token}, {len(feed_key.segments)} segments starting with {feed_key.segments[0]}')
        print(f"Tick spelling of 'NSE-2885': {self.normalizer.tick_spelling('NSE-2885')!r}")
        fields = [
            'last_quantity',
            'volume',
            'oi',
        ]
        exchanges = [
            'nse',
            'mcx',
        ]
        for exchange in exchanges:
            for field in fields:
                basis = self.normalizer.quantity_basis(exchange, field)
                print(f'{exchange} {field}: {basis}')
            print(f'{exchange} close policy: {self.normalizer.close_policy(exchange)}')
        try:
            TickNormalizer().feed_key('NSE-2885')
        except NotImplementedError:
            print('The base class alone cannot place a token: feed_key raises NotImplementedError')


if __name__ == '__main__':
    NewBrokerSubclassExample().run()
