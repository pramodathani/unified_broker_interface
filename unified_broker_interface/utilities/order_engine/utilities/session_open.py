"""When an instrument's trading day opens, which a volume-weighted order measures its half hours from."""

import datetime

from stock_brokers.instruments.mapping.utilities.segments import split_segment_value
from stock_brokers.instruments.ticks.utilities.sessions import EQUITY
from stock_brokers.instruments.ticks.utilities.sessions import session_for
from unified_broker_interface.utilities.exchange_calendar import TRADING_HOURS

EQUITY_OPENS_AT = datetime.time(9, 15)
OTHER_OPENS_AT = datetime.time(9, 0)


class SessionOpen:
    """The trading day of one segment: when it opens, and whether an equity day's volume shape fits it.

    NSE and BSE cash, indices and equity derivatives open at 09:15; currency derivatives and commodities open at 09:00, NCDEX at 10:00, all read from `TRADING_HOURS` in the exchange calendar. A segment that is unknown or empty is taken as equity, which is what the volume-weighted orders assumed before they read the segment.

    Attributes:
        segment (str): The exchange-prefixed segment, such as `mcx_futures`, or an empty string.
    """

    def __init__(self, segment):
        """Builds the trading day of a segment.

        Args:
            segment (str | None): The exchange-prefixed segment, or None or an empty string when the instrument has none.

        Returns:
            None: This method returns nothing.
        """
        self.segment = segment or ''

    def calendar(self):
        """The calendar the segment follows.

        Returns:
            str: `equity`, `currency` or `commodity`.
        """
        if not self.segment:
            return EQUITY
        return session_for(self.segment).calendar

    def is_equity(self):
        """Whether the segment trades on the equity day, whose volume shape the default profile describes.

        Returns:
            bool: True for equity.
        """
        return self.calendar() == EQUITY

    def opens_at(self):
        """When the segment's first trading session opens.

        Returns:
            datetime.time: The time of day in India.
        """
        calendar = self.calendar()
        exchange = ''
        if self.segment:
            exchange, _ = split_segment_value(self.segment)
        hours = (TRADING_HOURS.get(exchange) or {}).get(calendar)
        if hours:
            return datetime.time.fromisoformat(hours['sessions'][0]['opens'])
        if calendar == EQUITY:
            return EQUITY_OPENS_AT
        return OTHER_OPENS_AT
