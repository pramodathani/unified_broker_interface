"""Places Kotak Neo feed tokens, spelled `exchange_segment|token`, on the canonical segments they can be in.

A Kotak Neo token names its exchange segment before a bar. The cash segments `nse_cm` and `bse_cm` hold both shares and indices, and the `_fo`, `_cd` and `_co` segments hold derivatives. The segment is read without regard to case, so `BSE_CM|500325` works. A token with nothing after the bar, or a segment Kotak does not have, prints `None`.

The normalizer only works on the text of each token, so the program needs no Redis, database, network or stand-in of any kind. Each output line shows a token as the feed spells it, then the broker token that `unified.broker_mappings` is searched with, the order symbol when the broker names instruments by symbol, and how many canonical segments the search is limited to, with the first of them. A token the normalizer cannot place prints `None`.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/kotak/KotakTickNormalizer/example_1_placing_feed_tokens.py
"""

from stock_brokers.instruments.ticks.kotak import (
    KotakTickNormalizer,
)


class PlacingFeedTokensExample:
    """Asks the Kotak normalizer where each of a few feed tokens belongs.

    Attributes:
        normalizer (KotakTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as the feed spells them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = KotakTickNormalizer()
        self.tokens = [
            'nse_cm|2885',
            'nse_fo|35003',
            'mcx_fo|440001',
            'BSE_CM|500325',
            'nse_cm|',
            'nyse|1',
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
        print(f'Broker: {KotakTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')


if __name__ == '__main__':
    PlacingFeedTokensExample().run()
