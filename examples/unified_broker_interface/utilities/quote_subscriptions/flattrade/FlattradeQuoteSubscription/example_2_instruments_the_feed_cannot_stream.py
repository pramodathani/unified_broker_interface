"""Shows which instruments Flattrade's quote feed cannot be given.

Flattrade runs on Noren, which names an instrument by its own exchange name, a bar and the token.

This program builds the subscription spelling with no Redis client, because Flattrade's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. Noren has no cash or index exchange on MCX, so an MCX index is answered None, while a BSE option goes to `BFO`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/flattrade/FlattradeQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.flattrade import (
    FlattradeQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
    """Spells a few of Flattrade's mapping rows and prints each member.

    Attributes:
        spelling (FlattradeQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = FlattradeQuoteSubscription(None)
        self.rows = [
            (
                'an MCX index with no Noren cash exchange',
                {
                    'exchange': 'mcx',
                    'segment': 'mcx_commodity_indices',
                    'shape': 'security',
                },
                '99',
                None,
            ),
            (
                'a BSE stock option',
                {
                    'exchange': 'bse',
                    'segment': 'bse_equity_options',
                    'shape': 'option',
                },
                '870001',
                None,
            ),
        ]

    def run(self):
        """Prints the broker's name and every row's member.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {FlattradeQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    InstrumentsTheFeedCannotStreamExample().run()
