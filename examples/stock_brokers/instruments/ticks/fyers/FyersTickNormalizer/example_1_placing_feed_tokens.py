"""Places Fyers feed tokens, which are ticker symbols, on the canonical segments they can be in.

A Fyers tick names its instrument by the Fyers symbol rather than by a number, so the key carries no broker token: it carries the symbol as `order_symbol`, which the resolver turns into a token through the broker mappings. The normalizer decides the family from the symbol itself: MCX and names ending in FUT, CE or PE are derivatives, names ending in -INDEX are indices, and everything else is cash. An exchange Fyers does not serve, or a prefix with no name after it, prints `None`.

The normalizer only works on the text of each token, so the program needs no Redis, database, network or stand-in of any kind. Each output line shows a token as the feed spells it, then the broker token that `unified.broker_mappings` is searched with, the order symbol when the broker names instruments by symbol, and how many canonical segments the search is limited to, with the first of them. A token the normalizer cannot place prints `None`.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/fyers/FyersTickNormalizer/example_1_placing_feed_tokens.py
"""

from stock_brokers.instruments.ticks.fyers import (
    FyersTickNormalizer,
)


class PlacingFeedTokensExample:
    """Asks the Fyers normalizer where each of a few feed tokens belongs.

    Attributes:
        normalizer (FyersTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as the feed spells them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = FyersTickNormalizer()
        self.tokens = [
            'NSE:SBIN-EQ',
            'NSE:NIFTY50-INDEX',
            'NSE:NIFTY26SEPFUT',
            'MCX:CRUDEOIL26OCTFUT',
            'LSE:VOD',
            'NSE:',
        ]

    def describe(self, feed_key):
        """Describes a feed key in one line.

        Args:
            feed_key (FeedKey | None): The key the normalizer returned.

        Returns:
            str: The description.
        """
        if feed_key is None:
            return 'None'
        segment_count = len(feed_key.segments)
        first_segment = feed_key.segments[0]
        return f'broker_token={feed_key.broker_token!r} order_symbol={feed_key.order_symbol!r} segments={segment_count} starting with {first_segment}'

    def run(self):
        """Prints where each token belongs.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {FyersTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')


if __name__ == '__main__':
    PlacingFeedTokensExample().run()
