"""Places Groww feed tokens, spelled `EXCHANGE|SEGMENT|TOKEN`, on the canonical segments they can be in.

A Groww token has three parts: the exchange, Groww's own segment and the exchange token. Indices arrive on the CASH segment, so a CASH token is searched among both share and index segments. FNO and COMMODITY are derivatives. A token without all three parts, or with an exchange Groww does not serve, prints `None`.

The normalizer only works on the text of each token, so the program needs no Redis, database, network or stand-in of any kind. Each output line shows a token as the feed spells it, then the broker token that `unified.broker_mappings` is searched with, the order symbol when the broker names instruments by symbol, and how many canonical segments the search is limited to, with the first of them. A token the normalizer cannot place prints `None`.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/groww/GrowwTickNormalizer/example_1_placing_feed_tokens.py
"""

from stock_brokers.instruments.ticks.groww import (
    GrowwTickNormalizer,
)


class PlacingFeedTokensExample:
    """Asks the Groww normalizer where each of a few feed tokens belongs.

    Attributes:
        normalizer (GrowwTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as the feed spells them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = GrowwTickNormalizer()
        self.tokens = [
            'NSE|CASH|2885',
            'BSE|CASH|500325',
            'NSE|FNO|35003',
            'MCX|COMMODITY|440001',
            'NSE|2885',
            'NYSE|CASH|1',
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
        print(f'Broker: {GrowwTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')


if __name__ == '__main__':
    PlacingFeedTokensExample().run()
