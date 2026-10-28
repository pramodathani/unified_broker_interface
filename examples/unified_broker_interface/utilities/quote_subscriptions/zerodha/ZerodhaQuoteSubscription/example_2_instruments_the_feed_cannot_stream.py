"""Shows which instruments Zerodha's quote feed cannot be given.

Kite subscribes by the bare instrument token, whose low byte already names the exchange segment, so the identity is not needed.

This program builds the subscription spelling with no Redis client, because Zerodha's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. A token that is not a number is answered None, and spaces around a token are stripped.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/zerodha/ZerodhaQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.zerodha import (
    ZerodhaQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
    """Spells a few of Zerodha's mapping rows and prints each member.

    Attributes:
        spelling (ZerodhaQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = ZerodhaQuoteSubscription(None)
        self.rows = [
            (
                'a token that is not a number',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equities',
                    'shape': 'security',
                },
                'NSE:RELIANCE',
                None,
            ),
            (
                'a token with spaces around it',
                {
                    'exchange': 'nse',
                    'segment': 'nse_equities',
                    'shape': 'security',
                },
                ' 738561 ',
                None,
            ),
        ]

    def run(self):
        """Prints the broker's name and every row's member.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {ZerodhaQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    InstrumentsTheFeedCannotStreamExample().run()
