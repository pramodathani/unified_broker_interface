"""Places Kite instrument tokens on the segments their instruments can be in.

A Kite instrument token is an integer whose low byte names the segment: 1 is NSE cash, 7 is MCX and 9 is the indices of both exchanges. The normalizer reads that byte, so 738561 (RELIANCE) is searched among NSE cash segments, 256265 (NIFTY 50) among every index segment of NSE and BSE, and 5720583 among MCX derivatives. A token given as a string of digits works too, but text that is not a number, or a number whose low byte is a code Kite does not use, such as 264 (code 8), cannot be placed.

The normalizer only works on the text of each token, so the program needs no Redis, database, network or stand-in of any kind. Each output line shows a token as the feed spells it, then the broker token that `unified.broker_mappings` is searched with, the order symbol when the broker names instruments by symbol, and how many canonical segments the search is limited to, with the first of them. A token the normalizer cannot place prints `None`. A Kite subscription set stores tokens as strings, while ticks carry integers, so `tick_spelling` turns each string into the integer that plans are filed under.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/zerodha/ZerodhaTickNormalizer/example_1_placing_feed_tokens.py
"""

from stock_brokers.instruments.ticks.zerodha import (
    ZerodhaTickNormalizer,
)


class PlacingFeedTokensExample:
    """Asks the Zerodha normalizer where each of a few feed tokens belongs.

    Attributes:
        normalizer (ZerodhaTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as the feed spells them.
        subscription_tokens (list): Tokens as the broker's subscription set stores them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = ZerodhaTickNormalizer()
        self.tokens = [
            738561,
            256265,
            5720583,
            '408065',
            'NSE:INFY',
            264,
        ]
        self.subscription_tokens = [
            '738561',
            '256265',
            'NSE:INFY',
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
        print(f'Broker: {ZerodhaTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')
        print('Subscription tokens as ticks spell them:')
        for token in self.subscription_tokens:
            spelling = self.normalizer.tick_spelling(token)
            print(f'{token!r} -> {spelling!r}')


if __name__ == '__main__':
    PlacingFeedTokensExample().run()
