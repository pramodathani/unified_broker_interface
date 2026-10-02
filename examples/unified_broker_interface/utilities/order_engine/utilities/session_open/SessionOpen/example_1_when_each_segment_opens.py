"""Shows when the trading day opens for an equity, an index option, a currency future and three commodity futures, which a volume-weighted order counts its half hours from.

`SessionOpen` reads the segment's calendar from the tick pipeline's sessions and its first session's opening time from the exchange calendar's `TRADING_HOURS`. NSE equities and index options open at 09:15, NSE currency futures and MCX at 09:00, and NCDEX at 10:00. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/session_open/SessionOpen/example_1_when_each_segment_opens.py
"""

from unified_broker_interface.utilities.order_engine.utilities.session_open import (
    SessionOpen,
)


class WhenEachSegmentOpensExample:
    """Prints each segment's calendar and opening time.

    Attributes:
        segments (list): The exchange-prefixed segments shown.
    """

    def __init__(self):
        """Lists the segments.

        Returns:
            None: This method returns nothing.
        """
        self.segments = [
            'nse_equities',
            'nse_index_options',
            'nse_currency_futures',
            'mcx_commodity_futures',
            'bse_commodity_futures',
            'ncdex_futures',
        ]

    def run(self):
        """Prints one line per segment.

        Returns:
            None: This method returns nothing.
        """
        for segment in self.segments:
            session = SessionOpen(segment)
            print(f'{segment:<24} calendar {session.calendar():<10} opens at {session.opens_at()}')


if __name__ == '__main__':
    WhenEachSegmentOpensExample().run()
