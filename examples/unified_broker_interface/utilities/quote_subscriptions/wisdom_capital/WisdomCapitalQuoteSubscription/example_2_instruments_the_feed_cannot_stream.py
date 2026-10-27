"""Shows which instruments Wisdom Capital's quote feed cannot be given.

Wisdom Capital runs on Symphony XTS, which names an instrument by its exchange segment number, a colon and the exchange instrument id.

This program builds the subscription spelling with no Redis client, because Wisdom Capital's spelling never reads one, and prints the member for each instrument. It needs no data store, no network and no broker login.

Notice that `member` answers None for an instrument the feed cannot stream. XTS has no BSE commodity segment, so that instrument is answered None, while NSE currency goes to segment 3.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/wisdom_capital/WisdomCapitalQuoteSubscription/example_2_instruments_the_feed_cannot_stream.py
"""

from unified_broker_interface.utilities.quote_subscriptions.wisdom_capital import (
    WisdomCapitalQuoteSubscription,
)


class InstrumentsTheFeedCannotStreamExample:
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
                'a BSE commodity future',
                {
                    'exchange': 'bse',
                    'segment': 'bse_commodity_futures',
                    'shape': 'future',
                },
                '1',
                None,
            ),
            (
                'an NSE currency future',
                {
                    'exchange': 'nse',
                    'segment': 'nse_currency_futures',
                    'shape': 'future',
                },
                '1234',
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
    InstrumentsTheFeedCannotStreamExample().run()
