"""
When a tick may be a real trading tick, by exchange and kind of instrument.

Brokers keep their sockets open outside trading hours and send what they have: a reconnect on a
Sunday replays Friday's last state, and the exchanges' Saturday mock sessions stream prices that
never traded. Stored as live ticks those would be wrong twice over - wrong prices, and stamped with
a time at which nothing traded - so the unified service drops any tick received outside its
instrument's window.

The window is wider than the trading session on both sides. It opens at 09:00 India time to keep
the pre-open auction, and closes after the session to keep the closing prices brokers publish in
the minutes after it. `trading_close` is the session's own end, which a policy that trusts a
broker's `close` only while the session is running needs separately.

Which days trade comes from the exchanges' own calendars, one YAML file a year in `calendars/`,
generated from each exchange's publication. They are kept per exchange and per calendar, because the
segments of one exchange do not close together: currency derivatives also close on bank holidays the
equity segment trades through, and the commodity segments close their 09:00-17:00 morning session and
their 17:00 evening session separately - on most equity holidays the evening session still trades.
Special sessions, such as Muhurat trading on Diwali, open a window on a day that is otherwise closed.

A day missing from a calendar - a year whose file has not been added yet, or a closure announced
later by circular - is treated as a trading day. That costs at most one duplicate snapshot row per
instrument when a feed reconnects, because an unchanged tick is dropped by the pipeline's
de-duplication, whereas a trading day wrongly marked closed would lose a session.

Times are compared as seconds after midnight India time, computed from the epoch with a fixed
offset: India has no daylight saving, so the arithmetic is exact and costs nothing per tick.
"""

from collections import namedtuple
from datetime import date
from pathlib import Path

import yaml

from stock_brokers.instruments.mapping.utilities.segments import split_segment_value

INDIA_OFFSET_SECONDS = 19800
SECONDS_PER_DAY = 86400

# 1970-01-01 was a Thursday; with Monday as 0 that is day 3.
_EPOCH_WEEKDAY = 3

CALENDAR_DIRECTORY = Path(__file__).parent / "calendars"

EQUITY, CURRENCY, COMMODITY = "equity", "currency", "commodity"

# calendar: which holiday calendar the session follows. opens: when its window opens. evening_opens:
# where a commodity day splits into morning and evening sessions, or None for a single session.
# trading_close: the session's own end. window_close: when its window closes.
Session = namedtuple("Session", ["calendar", "opens", "evening_opens", "trading_close", "window_close"])

def _clock(hours, minutes=0, seconds=0):
    return hours * 3600 + minutes * 60 + seconds

# NSE and BSE cash, index and equity derivatives trade 09:15-15:30, with a 09:00 pre-open.
EQUITY_SESSION = Session(EQUITY, _clock(9), None, _clock(15, 30), _clock(16))

# Currency derivatives trade until 17:00.
CURRENCY_SESSION = Session(CURRENCY, _clock(9), None, _clock(17), _clock(17, 30))

# Commodity derivatives, on MCX and on the NSE and BSE commodity segments alike, trade a morning
# session 09:00-17:00 and an evening session 17:00-23:30, or 23:55 while the United States is on
# standard time. The window runs to midnight so neither close is cut off; trading_close is the later.
COMMODITY_SESSION = Session(COMMODITY, _clock(9), _clock(17), _clock(23, 55), _clock(23, 59, 59))

# NCDEX trades a morning session 10:00-17:00 and an evening session 17:00-21:00.
NCDEX_SESSION = Session(COMMODITY, _clock(9), _clock(17), _clock(21), _clock(21, 30))

# When a commodity day's evening session is closed, the window still runs this long past 17:00 to
# keep the morning session's closing prices.
EVENING_CLOSED_GRACE_SECONDS = 1800

def session_for(segment):
    """
    The session window an instrument's ticks are accepted in.

    Args:
        segment (str): The instrument's exchange-prefixed segment, for example "nse_currency_futures".

    Returns:
        Session: The window, in seconds after midnight India time, and the calendar it follows.
    """
    exchange, bare = split_segment_value(segment)
    if exchange == "ncdex":
        return NCDEX_SESSION
    if exchange == "mcx" or bare.startswith("commodit"):
        return COMMODITY_SESSION
    if bare.startswith("currenc"):
        return CURRENCY_SESSION
    return EQUITY_SESSION

def india_day_number(epoch):
    """
    The India trading day an instant falls on, as whole days since 1970-01-01.

    Args:
        epoch (float): Seconds since the Unix epoch.

    Returns:
        int: The day number.
    """
    return int((epoch + INDIA_OFFSET_SECONDS) // SECONDS_PER_DAY)

def india_date(epoch):
    """
    The India calendar date an instant falls on.

    Args:
        epoch (float): Seconds since the Unix epoch.

    Returns:
        datetime.date: The date.
    """
    return date.fromordinal(date(1970, 1, 1).toordinal() + india_day_number(epoch))

def day_start_epoch(day_number):
    """
    The instant India midnight begins a day.

    Args:
        day_number (int): Whole days since 1970-01-01, as india_day_number returns.

    Returns:
        float: Seconds since the Unix epoch.
    """
    return day_number * SECONDS_PER_DAY - INDIA_OFFSET_SECONDS

def _seconds(text):
    """"HH:MM" or "HH:MM:SS" as seconds after midnight."""
    parts = [int(part) for part in str(text).split(":")]
    return _clock(*parts)

class TradingCalendar:
    """
    The exchanges' holidays and special sessions, by exchange and calendar.

    Attributes:
        closures (dict): (exchange, calendar) to {date: "all" | "morning" | "evening"}.
        special_sessions (dict): (exchange, calendar) to {date: (opens, closes)} in seconds after midnight.
        years (list[int]): The years loaded.
    """

    def __init__(self, closures=None, special_sessions=None, years=()):
        """
        Build a calendar from its tables.

        Args:
            closures (dict | None): (exchange, calendar) to {date: "all" | "morning" | "evening"}.
            special_sessions (dict | None): (exchange, calendar) to {date: (opens, closes)}.
            years (tuple[int]): The years the tables cover.

        Returns:
            None: This function returns nothing.
        """
        self.closures = closures or {}
        self.special_sessions = special_sessions or {}
        self.years = sorted(years)

    @classmethod
    def load(cls, directory=CALENDAR_DIRECTORY):
        """
        Load every year's calendar file from a directory.

        Args:
            directory (pathlib.Path): The folder holding one `<year>.yaml` per year.

        Returns:
            TradingCalendar: The calendar.

        Raises:
            ValueError: If a file names a closure kind other than all, morning or evening.
        """
        closures, special_sessions, years = {}, {}, []
        for path in sorted(Path(directory).glob("*.yaml")):
            document = yaml.safe_load(path.read_text()) or {}
            years.append(document.get("year"))
            for exchange, calendars in (document.get("holidays") or {}).items():
                for calendar, entries in calendars.items():
                    for entry in entries or []:
                        if entry["closed"] not in ("all", "morning", "evening"):
                            raise ValueError(f"{path.name}: {exchange} {calendar} {entry['date']} closed is {entry['closed']!r}")
                        closures.setdefault((exchange, calendar), {})[entry["date"]] = entry["closed"]
            for entry in document.get("special_sessions") or []:
                window = (_seconds(entry["opens"]), _seconds(entry["closes"]))
                for exchange in entry["exchanges"]:
                    for calendar in entry["calendars"]:
                        special_sessions.setdefault((exchange, calendar), {})[entry["date"]] = window
        return cls(closures, special_sessions, years)

    @classmethod
    def empty(cls):
        """
        A calendar with no holidays and no special sessions: every weekday trades.

        Returns:
            TradingCalendar: The calendar.
        """
        return cls()

    def closure(self, exchange, calendar, day):
        """
        What of a day is closed.

        Args:
            exchange (str): Canonical exchange.
            calendar (str): EQUITY, CURRENCY or COMMODITY.
            day (datetime.date): The date.

        Returns:
            str | None: "all", "morning" or "evening", or None when the day is not a listed holiday.
        """
        return self.closures.get((exchange, calendar), {}).get(day)

    def special_session(self, exchange, calendar, day):
        """
        A special session held on a day, if any.

        Args:
            exchange (str): Canonical exchange.
            calendar (str): EQUITY, CURRENCY or COMMODITY.
            day (datetime.date): The date.

        Returns:
            tuple[int, int] | None: The window's opening and closing seconds after midnight, or None.
        """
        return self.special_sessions.get((exchange, calendar), {}).get(day)

_DEFAULT_CALENDAR = None

def default_calendar():
    """
    The calendar loaded from `calendars/`, read once per process.

    Returns:
        TradingCalendar: The calendar.
    """
    global _DEFAULT_CALENDAR
    if _DEFAULT_CALENDAR is None:
        _DEFAULT_CALENDAR = TradingCalendar.load()
    return _DEFAULT_CALENDAR

class SessionGate:
    """
    Answers "is this instant inside this instrument's window", fast enough to ask on every tick.

    What a day allows - closed, a whole session, only a morning or evening, or a special session's hours -
    is worked out once per exchange, session and India day and remembered, so the per-tick cost is one
    division, one modulo, a dictionary look-up and two comparisons.
    """

    def __init__(self, calendar=None):
        """
        Build the gate.

        Args:
            calendar (TradingCalendar | None): Holidays and special sessions, defaulting to the files in `calendars/`.

        Returns:
            None: This function returns nothing.
        """
        self._calendar = calendar if calendar is not None else default_calendar()
        self._windows = {}

    def window(self, exchange, session, day_number):
        """
        The seconds after midnight a day accepts ticks between, for an exchange's session.

        Args:
            exchange (str): Canonical exchange, for example "nse".
            session (Session): The instrument's session, from session_for.
            day_number (int): Whole days since 1970-01-01 in India time.

        Returns:
            tuple[int, int] | None: The first and last accepted second, or None when the day is closed.
        """
        key = (exchange, session, day_number)
        if key in self._windows:
            return self._windows[key]

        day = date.fromordinal(date(1970, 1, 1).toordinal() + day_number)
        special = self._calendar.special_session(exchange, session.calendar, day)
        if special is not None:
            window = special
        elif (day_number + _EPOCH_WEEKDAY) % 7 >= 5:
            window = None
        else:
            closed = self._calendar.closure(exchange, session.calendar, day)
            if closed is None:
                window = (session.opens, session.window_close)
            elif closed == "morning" and session.evening_opens is not None:
                window = (session.evening_opens, session.window_close)
            elif closed == "evening" and session.evening_opens is not None:
                window = (session.opens, session.evening_opens + EVENING_CLOSED_GRACE_SECONDS)
            else:
                window = None

        if len(self._windows) > 4096:
            self._windows.clear()
        self._windows[key] = window
        return window

    def is_trading_day(self, exchange, session, day_number):
        """
        Whether any part of a day trades for an exchange's session.

        Args:
            exchange (str): Canonical exchange.
            session (Session): The instrument's session.
            day_number (int): Whole days since 1970-01-01 in India time.

        Returns:
            bool: True when the day has a window.
        """
        return self.window(exchange, session, day_number) is not None

    def in_window(self, exchange, session, epoch):
        """
        Whether an instant is inside an instrument's accepted window.

        Args:
            exchange (str): Canonical exchange.
            session (Session): The instrument's session, from session_for.
            epoch (float): Seconds since the Unix epoch.

        Returns:
            bool: True when a tick received then should be kept.
        """
        shifted = epoch + INDIA_OFFSET_SECONDS
        window = self.window(exchange, session, int(shifted // SECONDS_PER_DAY))
        if window is None:
            return False
        seconds = shifted % SECONDS_PER_DAY
        return window[0] <= seconds <= window[1]

    def before_trading_close(self, session, epoch):
        """
        Whether an instant is before the session's own close on its day.

        Args:
            session (Session): The instrument's session.
            epoch (float): Seconds since the Unix epoch.

        Returns:
            bool: True before the close.
        """
        return (epoch + INDIA_OFFSET_SECONDS) % SECONDS_PER_DAY < session.trading_close

    def window_end_epoch(self, exchange, session, epoch):
        """
        The instant the window containing an instant closes.

        Args:
            exchange (str): Canonical exchange.
            session (Session): The instrument's session.
            epoch (float): Seconds since the Unix epoch.

        Returns:
            float: Seconds since the Unix epoch.
        """
        day_number = india_day_number(epoch)
        window = self.window(exchange, session, day_number)
        return day_start_epoch(day_number) + (window[1] if window else session.window_close)
