"""A trigger condition that holds after a time of day, or before one."""

from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)
from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)

KINDS = (
    'time_at',
    'time_after',
    'time_before',
    'time_from',
)


class TimeCondition:
    """A plan order's trigger condition tied to a time of day on the instrument's next trading day.

    `time_at` and `time_after` both hold from the time onwards, and `time_before` holds until it, which is how a price condition is kept to part of the day inside `all`. The time is worked out once, when the plan is placed, so a time that has already passed on a trading day is refused then, and a weekend or holiday rolls to the next trading day, as the `scheduled` type does. `time_from` is the same as `time_at` except that a time already passed today holds at once rather than being refused, as the closing price order starts at once when placed inside its window.

    Attributes:
        kind (str): One of `KINDS`.
        text (str): The time as the caller wrote it, such as `10:00`.
    """

    def __init__(self, kind, text):
        """Builds the condition.

        Args:
            kind (str): One of `KINDS`.
            text (str): The time, as `HH:MM` or `HH:MM:SS`.

        Returns:
            None: This method returns nothing.
        """
        self.kind = kind
        self.text = text

    def needs_prices(self):
        """Whether this condition reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def instruments(self):
        """The instruments this condition watches, which are none.

        Returns:
            list: An empty list.
        """
        return []

    def prepare(self, plan_order, memory):
        """Works out the moment the time falls on, and keeps it in the condition's memory.

        Args:
            plan_order (PlanOrder): The plan order, which knows its instrument's segment.
            memory (dict): The condition's memory, given `at`, the Unix time.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when the text is not a time, or names a time already passed on a trading day.
        """
        moments = Moments()
        segment = plan_order.trading_segment()
        if self.kind == 'time_from':
            now = moments.now()
            if TradingDays().is_trading_day(segment, now.date()):
                wanted = moments.read_time(self.text, self.kind)
                moment = now.replace(hour=wanted.hour, minute=wanted.minute, second=wanted.second, microsecond=0)
                if moment <= now:
                    memory['at'] = now.timestamp()
                    return
        moment, _ = moments.time_on_trading_day(
            self.text,
            self.kind,
            segment,
        )
        memory['at'] = moment

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the time has come, or for `time_before` whether it has not yet.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): The condition's memory, holding `at`.
            quotes (dict): Unused.
            now (float): The Unix time of the tick.
            opening_side (str): Unused.
            sending_side (str): Unused.

        Returns:
            bool: True when the condition holds now.
        """
        del plan_order, quotes, opening_side, sending_side
        moment = memory.get('at')
        if moment is None:
            return False
        if self.kind == 'time_before':
            return now < moment
        return now >= moment

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The kind and the time.
        """
        return {
            self.kind: self.text,
        }
