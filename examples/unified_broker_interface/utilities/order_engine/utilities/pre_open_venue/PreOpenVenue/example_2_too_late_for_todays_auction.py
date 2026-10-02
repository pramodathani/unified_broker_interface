"""Checks an opening auction order taken at different moments, and one whose time falls outside collection.

`PreOpenVenue.check` lets an order through before collection closes, and on a day the exchange does not trade, since the order then waits for the next pre-open. It refuses one taken after collection has closed on a trading day, naming the next trading day, and one whose `at_time` the pre-open would not take.

An engine that was down at `at_time` fires the order at its first tick afterwards, and sent then it would trade in continuous trading instead of the auction. So `has_closed` is asked at that tick, with the tick's Unix time, whether collection has closed on that day: at 09:08 IST it has not, and at 09:10 IST and 09:20 IST it has, so the order must not be sent.

The calendar is read from the exchange calendar files; nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/pre_open_venue/PreOpenVenue/example_2_too_late_for_todays_auction.py
"""

import datetime
import zoneinfo

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.pre_open_venue import (
    PreOpenVenue,
)


class StandInInstrument:
    """Stands in for the instrument the placement reads.

    Attributes:
        exchange (str): The exchange, such as `nse`.
        bare_segment (str): The segment without its exchange.
        segment (str): The exchange-prefixed segment.
    """

    def __init__(self, exchange, bare_segment):
        """Builds the instrument.

        Args:
            exchange (str): The exchange.
            bare_segment (str): The segment without its exchange.

        Returns:
            None: This method returns nothing.
        """
        self.exchange = exchange
        self.bare_segment = bare_segment
        self.segment = f'{exchange}_{bare_segment}'


class StandInPlacement:
    """Stands in for the placement, answering one instrument.

    Attributes:
        instrument (StandInInstrument): The instrument.
    """

    def __init__(self, instrument):
        """Builds the placement.

        Args:
            instrument (StandInInstrument): The instrument.

        Returns:
            None: This method returns nothing.
        """
        self.instrument = instrument

    def market_context(self, instrument_id, with_quote, with_positions):
        """The instrument, as the placement answers it.

        Args:
            instrument_id (str): Unused.
            with_quote (bool): Unused.
            with_positions (bool): Unused.

        Returns:
            tuple: The instrument and two unused values.
        """
        del instrument_id, with_quote, with_positions
        return self.instrument, None, None


class StandInContext:
    """Stands in for the order's view of the plan order.

    Attributes:
        instrument_id (str): The order's instrument.
        body (dict): The order's settings.
        placement (StandInPlacement): The placement.
    """

    def __init__(self, exchange, bare_segment, order_type):
        """Builds the context.

        Args:
            exchange (str): The instrument's exchange.
            bare_segment (str): The instrument's segment without its exchange.
            order_type (str): The order type.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = f'{exchange}:{bare_segment}'
        self.body = {
            'order_type': order_type,
            'validity': 'DAY',
        }
        self.placement = StandInPlacement(StandInInstrument(exchange, bare_segment))

    def trading_segment(self):
        """The instrument's exchange-prefixed segment.

        Returns:
            str: The segment.
        """
        return self.placement.instrument.segment


INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class TooLateForTodaysAuctionExample:
    """Checks four moments and one bad time, then asks at three ticks whether collection has closed."""

    def run(self):
        """Prints whether each check passes, and whether collection has closed at each tick.

        Returns:
            None: This method returns nothing.
        """
        context = StandInContext('nse', 'equities', 'LIMIT')
        venue = PreOpenVenue('09:00:30')
        moments = [
            datetime.datetime(2026, 9, 23, 8, 45),
            datetime.datetime(2026, 9, 23, 9, 8),
            datetime.datetime(2026, 9, 23, 10, 0),
            datetime.datetime(2026, 9, 27, 10, 0),
        ]
        for now in moments:
            self.show(venue, context, now)
        self.show(PreOpenVenue('09:12:00'), context, moments[0])
        ticks = [
            datetime.datetime(2026, 9, 23, 9, 8, tzinfo=INDIA),
            datetime.datetime(2026, 9, 23, 9, 10, tzinfo=INDIA),
            datetime.datetime(2026, 9, 23, 9, 20, tzinfo=INDIA),
        ]
        for tick in ticks:
            print(f'has_closed at a tick at {tick:%H:%M} IST, Unix time {tick.timestamp():.0f}: {venue.has_closed(context, tick.timestamp())}')

    def show(self, venue, context, now):
        """Prints one check.

        Args:
            venue (PreOpenVenue): The venue.
            context (StandInContext): The order.
            now (datetime.datetime): The moment it is taken.

        Returns:
            None: This method returns nothing.
        """
        label = f'at_time {venue.at_time}, taken {now:%a %Y-%m-%d %H:%M}'
        try:
            venue.check(context, now)
        except RefusedRequestError as error:
            print(f'{label}: refused ({error})')
            return
        print(f'{label}: taken')


if __name__ == '__main__':
    TooLateForTodaysAuctionExample().run()
