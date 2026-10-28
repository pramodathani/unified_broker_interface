"""Shows which instruments INDmoney's quote feed cannot be given.

INDmoney names an instrument by the segment its market feed uses, a colon and the token, and only on segments whose INDstocks quotes are trusted.

This program builds the subscription spelling with no Redis client, because INDmoney's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. A dual-listed stock's BSE code is answered with its NSE quote, and INDstocks has no MCX segment, so both are answered None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/indmoney/IndmoneyQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.indmoney import (
    IndmoneyQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
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
                'a BSE equity',
                {
                    'exchange': 'bse',
                    'segment': 'bse_equities',
                    'shape': 'security',
                },
                '500325',
                None,
            ),
            (
                'an MCX future',
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
        print(f'Broker: {IndmoneyQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    InstrumentsTheFeedCannotStreamExample().run()
