"""Reading the times an order type is told to act at, in the timezone the exchanges keep."""

import datetime
import zoneinfo

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class Moments:
    """Turns `"15:10"` or `"15:10:30"` into a moment today, and durations into moments from now.

    Every time an order type is given is a wall-clock time on an Indian exchange's day, because that is how somebody says it: square off at ten past three, not at an epoch. So the text is read in `Asia/Kolkata` whatever the machine's own timezone is, which matters because a server keeping UTC would otherwise square off five and a half hours late.

    A time already past today is refused rather than quietly meaning tomorrow. An order told to act at a time that has gone is far more likely to be a mistake than an instruction to wait eighteen hours, and waiting eighteen hours with a live position is not something to do by inference.
    """

    def now(self):
        """The moment now, in India.

        Returns:
            datetime.datetime: Now, with the Indian offset.
        """
        return datetime.datetime.now(INDIA)

    def time_today(self, text, field_name, now=None):
        """A wall-clock time today, as an epoch.

        Args:
            text (str): The time, as `HH:MM` or `HH:MM:SS`.
            field_name (str): The field's name, for the message.
            now (datetime.datetime | None): The moment to reckon from, or None for now.

        Returns:
            float: The epoch of that time today, in India.

        Raises:
            RefusedRequestError: With HTTP 400 when the text is not a time, or names a time that has already passed.
        """
        now = now or self.now()
        wanted = self.read_time(text, field_name)
        moment = now.replace(
            hour=wanted.hour,
            minute=wanted.minute,
            second=wanted.second,
            microsecond=0,
        )
        if moment <= now:
            raise RefusedRequestError.refusal(
                f'{field_name} of {text} has already passed today, and an '
                'order is not held overnight on the strength of a time that '
                'has gone',
                400,
            )
        return moment.timestamp()

    def read_time(self, text, field_name):
        """A wall-clock time as the caller wrote it.

        Args:
            text (str): The time, as `HH:MM` or `HH:MM:SS`.
            field_name (str): The field's name, for the message.

        Returns:
            datetime.time: The time.

        Raises:
            RefusedRequestError: With HTTP 400 when the text is not a time.
        """
        try:
            return datetime.time.fromisoformat(str(text))
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'{field_name} must be a time of day such as 15:10, not '
                f'{text!r}',
                400,
            )

    def time_on_trading_day(self, text, field_name, segment, now=None):
        """A wall-clock time on the instrument's next trading day: today when today trades, otherwise the next day that does.

        On a weekend or an exchange holiday a time such as `15:00` means that time on the next trading day, because nothing can trade before then. On a trading day it is today's time, refused when it has already passed, as `time_today` refuses it.

        Args:
            text (str): The time, as `HH:MM` or `HH:MM:SS`.
            field_name (str): The field's name, for the message.
            segment (str): The instrument's exchange-prefixed segment, such as `nse_equities`.
            now (datetime.datetime | None): The moment to reckon from, or None for now.

        Returns:
            tuple: The epoch of that time (float) and the day it falls on (datetime.date).

        Raises:
            RefusedRequestError: With HTTP 400 when the text is not a time, or names a time that has already passed on a trading day.
        """
        now = now or self.now()
        today = now.date()
        trading_days = TradingDays()
        if trading_days.is_trading_day(segment, today):
            return self.time_today(text, field_name, now), today
        wanted = self.read_time(text, field_name)
        day = trading_days.next_trading_day(segment, today)
        moment = datetime.datetime.combine(day, wanted, INDIA)
        return moment.timestamp(), day

    def described(self, text, day, now=None):
        """A time as an answer shows it: the caller's own text when it is today, and with its date when it is not.

        Args:
            text (str): The time as the caller wrote it.
            day (datetime.date): The day it falls on.
            now (datetime.datetime | None): The moment to reckon from, or None for now.

        Returns:
            str: The description, such as `15:00` or `15:00 on 2026-09-28`.
        """
        now = now or self.now()
        if day == now.date():
            return str(text)
        return f'{text} on {day.isoformat()}'

    def minutes_from_now(self, value, field_name, now=None):
        """A number of minutes from now, as an epoch.

        Args:
            value (object): The number of minutes.
            field_name (str): The field's name, for the message.
            now (datetime.datetime | None): The moment to reckon from, or None for now.

        Returns:
            float: The epoch.

        Raises:
            RefusedRequestError: With HTTP 400 when the value is not a positive number of minutes.
        """
        now = now or self.now()
        try:
            minutes = float(value)
        except (TypeError, ValueError):
            minutes = None
        if minutes is None or minutes <= 0:
            raise RefusedRequestError.refusal(
                f'{field_name} must be a number of minutes above zero, not '
                f'{value!r}',
                400,
            )
        return now.timestamp() + minutes * 60
