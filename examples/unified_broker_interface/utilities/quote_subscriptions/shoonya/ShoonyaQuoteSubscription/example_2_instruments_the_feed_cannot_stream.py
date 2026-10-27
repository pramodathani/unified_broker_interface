"""Shows which instruments Shoonya's quote feed cannot be given.

Shoonya runs on Noren, which names an instrument by its own exchange name, a bar and the token.

This program builds the subscription spelling with no Redis client, because Shoonya's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. An exchange Noren does not know is answered None; NCDEX derivatives go to `NCX`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/shoonya/ShoonyaQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.shoonya import (
    ShoonyaQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
    """Spells a few of Shoonya's mapping rows and prints each member.

    Attributes:
        spelling (ShoonyaQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = ShoonyaQuoteSubscription(None)
        self.rows = [
            (
                'an instrument on an unknown exchange',
                {
                    'exchange': 'nsix',
                    'segment': 'nsix_equities',
                    'shape': 'security',
                },
                '1',
                None,
            ),
            (
                'an NCDEX future',
                {
                    'exchange': 'ncdex',
                    'segment': 'ncdex_commodity_futures',
                    'shape': 'future',
                },
                '4100',
                None,
            ),
        ]

    def run(self):
        """Prints the broker's name and every row's member.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {ShoonyaQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    InstrumentsTheFeedCannotStreamExample().run()
