"""Places Wisdom Capital feed tokens, which name the XTS exchange segment by number or by name, on the canonical segments they can be in.

Wisdom Capital runs on the XTS platform, whose tokens are `SEGMENT:INSTRUMENT_ID`. The segment is a number, such as 1 for NSE cash and 51 for MCX, but some payloads spell it by name, such as `NSECM`, and the normalizer accepts both. A segment number XTS does not use, or a segment with no instrument id after it, prints `None`.

The normalizer only works on the text of each token, so the program needs no Redis, database, network or stand-in of any kind. Each output line shows a token as the feed spells it, then the broker token that `unified.broker_mappings` is searched with, the order symbol when the broker names instruments by symbol, and how many canonical segments the search is limited to, with the first of them. A token the normalizer cannot place prints `None`. `tick_spelling` turns a subscription token spelled by segment name into the numeric spelling ticks carry, keeps a numeric spelling as it is, and refuses a name it does not know.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/wisdom_capital/WisdomCapitalTickNormalizer/example_1_placing_feed_tokens.py
"""

from stock_brokers.instruments.ticks.wisdom_capital import (
    WisdomCapitalTickNormalizer,
)


class PlacingFeedTokensExample:
    """Asks the Wisdom Capital normalizer where each of a few feed tokens belongs.

    Attributes:
        normalizer (WisdomCapitalTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as the feed spells them.
        subscription_tokens (list): Tokens as the broker's subscription set stores them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = WisdomCapitalTickNormalizer()
        self.tokens = [
            '1:2885',
            'NSECM:2885',
            '2:35003',
            '51:440001',
            '21:12345',
            '99:1',
            'NSECM:',
        ]
        self.subscription_tokens = [
            'NSECM:2885',
            'MCXFO:440001',
            '1:2885',
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
        print(f'Broker: {WisdomCapitalTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')
        print('Subscription tokens as ticks spell them:')
        for token in self.subscription_tokens:
            spelling = self.normalizer.tick_spelling(token)
            print(f'{token!r} -> {spelling!r}')


if __name__ == '__main__':
    PlacingFeedTokensExample().run()
