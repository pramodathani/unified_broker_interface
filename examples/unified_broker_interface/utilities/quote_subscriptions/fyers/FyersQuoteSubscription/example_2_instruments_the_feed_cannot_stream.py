"""Shows which instruments Fyers's quote feed cannot be given.

Fyers subscribes by its symbol, which the mapping keeps as the order symbol, so the broker token is not needed.

This program builds the subscription spelling with no Redis client, because Fyers's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. The Fyers tick normalizer does not read currency derivatives, and a mapping without a symbol cannot be subscribed, so both are answered None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/fyers/FyersQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.fyers import (
    FyersQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
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
                'an NSE currency future',
                {
                    'exchange': 'nse',
                    'segment': 'nse_currency_futures',
                    'shape': 'future',
                },
                '1012',
                'NSE:USDINR26NOVFUT',
            ),
            (
                'a mapping with no order symbol',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equities',
                    'shape': 'security',
                },
                '10100000002885',
                None,
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
    InstrumentsTheFeedCannotStreamExample().run()
