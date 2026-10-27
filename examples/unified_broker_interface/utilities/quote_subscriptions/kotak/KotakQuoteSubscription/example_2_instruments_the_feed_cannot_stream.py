"""Shows which instruments Kotak's quote feed cannot be given.

Kotak names an instrument by its lowercase exchange segment, a bar and the token, choosing the segment the way Kotak's REST quotes do.

This program builds the subscription spelling with no Redis client, because Kotak's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. Kotak has no segment for NCDEX, so that instrument is answered None, while a BSE equity goes to `bse_cm`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/kotak/KotakQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.kotak import (
    KotakQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
    """Spells a few of Kotak's mapping rows and prints each member.

    Attributes:
        spelling (KotakQuoteSubscription): The spelling being shown.
        rows (list): Each row's label, identity, broker token and order symbol.
    """

    def __init__(self):
        """Builds the spelling and the rows.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = KotakQuoteSubscription(None)
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
                'a BSE equity',
                {
                    'exchange': 'bse',
                    'segment': 'bse_equities',
                    'shape': 'security',
                },
                '500325',
                None,
            ),
        ]

    def run(self):
        """Prints the broker's name and every row's member.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {KotakQuoteSubscription.BROKER_NAME}')
        for label, identity, broker_token, order_symbol in self.rows:
            member = self.spelling.member(identity, broker_token, order_symbol)
            print(f'{label} ({identity["segment"]}): {member}')


if __name__ == '__main__':
    InstrumentsTheFeedCannotStreamExample().run()
