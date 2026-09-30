"""Places Shoonya feed tokens, spelled `EXCHANGE|TOKEN`, on the canonical segments they can be in.

Shoonya runs on the Noren platform, so it inherits everything from `NorenTickNormalizer` and only sets its broker name. The exchange before the bar decides the family: MCX and NCX (NCDEX) are commodity derivatives, BFO is BSE derivatives, and BSE is BSE shares and indices together. A token without the bar, or with no exchange before it, prints `None`.

The normalizer only works on the text of each token, so the program needs no Redis, database, network or stand-in of any kind. Each output line shows a token as the feed spells it, then the broker token that `unified.broker_mappings` is searched with, the order symbol when the broker names instruments by symbol, and how many canonical segments the search is limited to, with the first of them. A token the normalizer cannot place prints `None`.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/shoonya/ShoonyaTickNormalizer/example_1_placing_feed_tokens.py
"""

from stock_brokers.instruments.ticks.shoonya import (
    ShoonyaTickNormalizer,
)


class PlacingFeedTokensExample:
    """Asks the Shoonya normalizer where each of a few feed tokens belongs.

    Attributes:
        normalizer (ShoonyaTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as the feed spells them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = ShoonyaTickNormalizer()
        self.tokens = [
            'MCX|440001',
            'NCX|12345',
            'BFO|1135101',
            'BSE|500325',
            'NSE 2885',
            '|2885',
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
        print(f'Broker: {ShoonyaTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')


if __name__ == '__main__':
    PlacingFeedTokensExample().run()
