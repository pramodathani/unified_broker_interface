"""Spells three of Shoonya's instruments the way its quote websocket subscribes them.

Shoonya runs on Noren, which names an instrument by its own exchange name, a bar and the token.

This program builds the subscription spelling with no Redis client, because Shoonya's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that each member is in the spelling the broker's `bin/<broker>/instruments/websocket_quotes` reads from its Redis subscription set.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/shoonya/ShoonyaQuoteSubscription/example_1_spelling_instruments.py
"""

from unified_broker_interface.utilities.quote_subscriptions.shoonya import (
    ShoonyaQuoteSubscription,
)


class SpellingInstrumentsExample:
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
                'RELIANCE',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equities',
                    'shape': 'security',
                },
                '2885',
                None,
            ),
            (
                'SENSEX 26 NOV 80000 PE',
                {
                    'exchange': 'bse',
                    'segment': 'bse_equity_index_options',
                    'shape': 'option',
                },
                '870002',
                None,
            ),
            (
                'CRUDEOIL 26 NOV FUT',
                {
                    'exchange': 'mcx',
                    'segment': 'mcx_commodity_futures',
                    'shape': 'future',
                },
                '428000',
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
    SpellingInstrumentsExample().run()
