"""Reading the times an order type is told to act at, in the timezone the exchanges keep."""

import datetime
import zoneinfo

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
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
        try:
            wanted = datetime.time.fromisoformat(str(text))
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'{field_name} must be a time of day such as 15:10, not '
                f'{text!r}',
                400,
            )
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
