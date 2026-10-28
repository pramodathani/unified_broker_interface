"""Spells three of INDmoney's instruments the way its quote websocket subscribes them.

INDmoney names an instrument by the segment its market feed uses, a colon and the token, and only on segments whose INDstocks quotes are trusted.

This program builds the subscription spelling with no Redis client, because INDmoney's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that each member is in the spelling the broker's `bin/<broker>/instruments/websocket_quotes` reads from its Redis subscription set.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/indmoney/IndmoneyQuoteSubscription/example_1_spelling_instruments.py
"""

from unified_broker_interface.utilities.quote_subscriptions.indmoney import (
    IndmoneyQuoteSubscription,
)


class SpellingInstrumentsExample:
    """Spells a few of INDmoney's mapping rows and prints each member.

    Attributes:
        spelling (IndmoneyQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = IndmoneyQuoteSubscription(None)
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
                'NIFTY 50',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equity_indices',
                    'shape': 'security',
                },
                '13',
                None,
            ),
            (
                'RELIANCE 26 NOV 3000 CE',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equity_options',
                    'shape': 'option',
                },
                '41001',
                None,
            ),
        ]

    def run(self):
        """Prints the broker's name and every row's member.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {IndmoneyQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    SpellingInstrumentsExample().run()
