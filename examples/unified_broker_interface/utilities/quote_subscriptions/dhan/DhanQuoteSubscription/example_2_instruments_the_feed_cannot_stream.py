"""Shows which instruments Dhan's quote feed cannot be given.

Dhan spells a member as its segment name, a colon and the security id, choosing the segment the way Dhan's REST quotes do.

This program builds the subscription spelling with no Redis client, because Dhan's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. Dhan has no segment for NCDEX, so that instrument is answered None and the allocation passes Dhan over for it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/dhan/DhanQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.dhan import (
    DhanQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
    """Spells a few of Dhan's mapping rows and prints each member.

    Attributes:
        spelling (DhanQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = DhanQuoteSubscription(None)
        self.rows = [
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
            (
                'an MCX commodity future',
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
        print(f'Broker: {DhanQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    InstrumentsTheFeedCannotStreamExample().run()
