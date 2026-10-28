"""Spells three of Fyers's instruments the way its quote websocket subscribes them.

Fyers subscribes by its symbol, which the mapping keeps as the order symbol, so the broker token is not needed.

This program builds the subscription spelling with no Redis client, because Fyers's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that each member is in the spelling the broker's `bin/<broker>/instruments/websocket_quotes` reads from its Redis subscription set.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/fyers/FyersQuoteSubscription/example_1_spelling_instruments.py
"""

from unified_broker_interface.utilities.quote_subscriptions.fyers import (
    FyersQuoteSubscription,
)


class SpellingInstrumentsExample:
    """Spells a few of Fyers's mapping rows and prints each member.

    Attributes:
        spelling (FyersQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = FyersQuoteSubscription(None)
        self.rows = [
            (
                'RELIANCE',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equities',
                    'shape': 'security',
                },
                '10100000002885',
                'NSE:RELIANCE-EQ',
            ),
            (
                'NIFTY 26 NOV 24000 CE',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equity_index_options',
                    'shape': 'option',
                },
                '101126112435001',
                'NSE:NIFTY26NOV24000CE',
            ),
            (
                'GOLD 26 DEC FUT',
                {
                    'exchange': 'mcx',
                    'segment': 'mcx_commodity_futures',
                    'shape': 'future',
                },
                '1120261205565899',
                'MCX:GOLD26DECFUT',
            ),
        ]

    def run(self):
        """Prints the broker's name and every row's member.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {FyersQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    SpellingInstrumentsExample().run()
