"""Places a token from every exchange the Noren platform names on the canonical segments it can be in.

Flattrade and Shoonya both run on the Noren platform, and `NorenTickNormalizer` holds everything they share: a token is `EXCHANGE|TOKEN`, and the exchange name decides where the instrument is searched for. NSE and BSE hold shares and indices together; NFO, CDS and NCO are NSE's equity, currency and commodity derivatives; BFO and BCD are BSE's; MCX is MCX; and NCDEX is spelt either NCX or NCDEX. The exchange is read without regard to case and surrounding spaces are ignored.

The shared class sets no broker name, because each broker's subclass does; it is used here directly because placing a token does not depend on which Noren broker sent it. The normalizer only works on the text of each token, so no data store, network or stand-in is needed. Each line shows the token, the broker token the mappings are searched with, and how many canonical segments are searched, with the first of them. A token the normalizer cannot place prints `None`.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/noren/NorenTickNormalizer/example_1_every_noren_exchange.py
"""

from stock_brokers.instruments.ticks.noren import (
    NorenTickNormalizer,
)


class EveryNorenExchangeExample:
    """Places one token from each Noren exchange.

    Attributes:
        normalizer (NorenTickNormalizer): The normalizer being shown.
        tokens (list): The tokens to place, spelled as a Noren feed spells them.
    """

    def __init__(self):
        """Builds the normalizer and the tokens to place.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = NorenTickNormalizer()
        self.tokens = [
            'NSE|2885',
            'BSE|500325',
            'NFO|35003',
            'CDS|1573',
            'NCO|2003',
            'BFO|1135101',
            'BCD|8001',
            'MCX|440001',
            'NCX|12345',
            'NCDEX|12345',
            ' mcx | 440001 ',
            'LME|1',
            'NSE|',
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
        return f'broker_token={feed_key.broker_token!r} segments={segment_count} starting with {first_segment}'

    def run(self):
        """Prints where each token belongs.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker name on the shared class: {NorenTickNormalizer.BROKER_NAME}')
        for token in self.tokens:
            feed_key = self.normalizer.feed_key(token)
            print(f'{token!r} -> {self.describe(feed_key)}')


if __name__ == '__main__':
    EveryNorenExchangeExample().run()
