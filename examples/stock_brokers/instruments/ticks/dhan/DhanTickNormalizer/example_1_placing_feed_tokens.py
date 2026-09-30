"""Places Dhan feed tokens, which name the exchange segment by number, on the canonical segments they can be in.

Dhan names an instrument by an exchange segment and a security id. Its market feed spells the segment as the numeric code from the packet header, `5:565899`, while its subscription set spells it by name, `MCX_COMM:565899`, and the normalizer accepts both. The security id alone is not enough, because Dhan reuses it across segments: 2885 is RELIANCE on NSE cash (code 1) and something else among NSE derivatives (code 2), so the key always carries the segments to search. Code 6 is not a Dhan segment and a token without a security id is malformed, so both print `None`.

The normalizer only works on the text of each token, so the program needs no Redis, database, network or stand-in of any kind. Each output line shows a token as the feed spells it, then the broker token that `unified.broker_mappings` is searched with, the order symbol when the broker names instruments by symbol, and how many canonical segments the search is limited to, with the first of them. A token the normalizer cannot place prints `None`. `tick_spelling` does the reverse translation for the subscription set: it turns a segment name into the number ticks carry, keeps a numeric spelling as it is, and refuses a name it does not know.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/dhan/DhanTickNormalizer/example_1_placing_feed_tokens.py
"""

from stock_brokers.instruments.ticks.dhan import (
    DhanTickNormalizer,
)


class PlacingFeedTokensExample:
    """Asks the Dhan normalizer where each of a few feed tokens belongs.

    Attributes:
        normalizer (DhanTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as the feed spells them.
        subscription_tokens (list): Tokens as the broker's subscription set stores them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = DhanTickNormalizer()
        self.tokens = [
            '5:565899',
            'MCX_COMM:565899',
            '1:2885',
            '2:2885',
            '0:13',
            '6:100',
            'NSE_EQ',
        ]
        self.subscription_tokens = [
            'MCX_COMM:565899',
            'NSE_EQ:2885',
            '5:565899',
            'XYZ:1',
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
        print(f'Broker: {DhanTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')
        print('Subscription tokens as ticks spell them:')
        for token in self.subscription_tokens:
            spelling = self.normalizer.tick_spelling(token)
            print(f'{token!r} -> {spelling!r}')


if __name__ == '__main__':
    PlacingFeedTokensExample().run()
