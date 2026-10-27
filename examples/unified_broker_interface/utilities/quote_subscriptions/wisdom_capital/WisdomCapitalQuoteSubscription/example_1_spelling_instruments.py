"""Spells three of Wisdom Capital's instruments the way its quote websocket subscribes them.

Wisdom Capital runs on Symphony XTS, which names an instrument by its exchange segment number, a colon and the exchange instrument id.

This program builds the subscription spelling with no Redis client, because Wisdom Capital's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that each member is in the spelling the broker's `bin/<broker>/instruments/websocket_quotes` reads from its Redis subscription set.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/wisdom_capital/WisdomCapitalQuoteSubscription/example_1_spelling_instruments.py
"""

from unified_broker_interface.utilities.quote_subscriptions.wisdom_capital import (
    WisdomCapitalQuoteSubscription,
)


class SpellingInstrumentsExample:
    """Spells a few of Wisdom Capital's mapping rows and prints each member.

    Attributes:
        spelling (WisdomCapitalQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = WisdomCapitalQuoteSubscription(None)
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
                'NIFTY 26 NOV 24000 CE',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equity_index_options',
                    'shape': 'option',
                },
                '35001',
                None,
            ),
            (
                'GOLD 26 DEC FUT',
                {
                    'exchange': 'mcx',
                    'segment': 'mcx_commodity_futures',
                    'shape': 'future',
                },
                '565899',
                None,
            ),
        ]

    def run(self):
        """Prints the broker's name and every row's member.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {WisdomCapitalQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    SpellingInstrumentsExample().run()
