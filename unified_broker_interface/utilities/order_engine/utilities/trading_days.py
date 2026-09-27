"""Which dates an instrument's exchange trades on, for the order types that act at a time of day."""

import datetime

from stock_brokers.instruments.ticks.utilities.sessions import SessionGate
from stock_brokers.instruments.ticks.utilities.sessions import session_for

MOST_DAYS_AHEAD = 30
EPOCH_DATE = datetime.date(1970, 1, 1)


class TradingDays:
    """Answers whether a date trades for an instrument's segment, and which trading day comes next.

    It reads the same exchange calendars the tick pipeline uses, through `SessionGate`: weekends, each exchange's holidays for its equity, currency or commodity calendar, and special sessions such as Muhurat trading. A day on which only a commodity morning or evening session is closed still counts as a trading day, because part of it trades.

    Attributes:
        gate (SessionGate): The session gate the answers come from.
    """

    def __init__(self, gate=None):
        """Builds the calendar reader.

        Args:
            gate (SessionGate | None): The gate to ask, or None for one over the calendar files.

        Returns:
            None: This method returns nothing.
        """
        self.gate = gate if gate is not None else SessionGate()

    def is_trading_day(self, segment, day):
        """Whether any part of a day trades for a segment.

        Args:
            segment (str): The exchange-prefixed segment, such as `nse_equities`.
            day (datetime.date): The date.

        Returns:
            bool: True when the day trades.
        """
        exchange = str(segment or '').partition('_')[0]
        day_number = (day - EPOCH_DATE).days
        return self.gate.is_trading_day(exchange, session_for(segment), day_number)

    def next_trading_day(self, segment, after):
        """The first trading day after a date.

        Args:
            segment (str): The exchange-prefixed segment.
            after (datetime.date): The date to count from, not itself included.

        Returns:
            datetime.date: The next trading day.

        Raises:
            ValueError: When none of the next thirty days trades, which means the calendar files are missing or wrong.
        """
        day = after
        for _ in range(MOST_DAYS_AHEAD):
            day = day + datetime.timedelta(days=1)
            if self.is_trading_day(segment, day):
                return day
        raise ValueError(
            f'no trading day was found for {segment} in the {MOST_DAYS_AHEAD} days after {after}'
        )
