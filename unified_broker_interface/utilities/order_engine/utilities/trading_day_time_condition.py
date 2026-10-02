"""A trigger condition that holds from a time of day on a chosen trading day counted from when the plan is placed."""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)


class TradingDayTimeCondition:
    """A plan order's trigger that holds from a time of day on one trading day of a run of them, for a Repeat join's copies sent every trading day.

    The first trading day of the run is today when today trades and the time has not passed yet, and otherwise the next trading day; `day_index` counts trading days on from it, so copy 0 goes on the first, copy 1 on the trading day after, and so on, weekends and the exchange's holidays skipped. The moment is worked out once, when the plan is placed, and kept in memory, so a restart keeps it.

    Attributes:
        text (str): The time of day as the caller wrote it, such as `09:20`.
        day_index (int): How many trading days after the first this copy goes.
    """

    def __init__(self, text, day_index):
        """Builds the condition from a time the plan reader has already checked.

        Args:
            text (str): The time, as `HH:MM` or `HH:MM:SS`.
            day_index (int): How many trading days after the first.

        Returns:
            None: This method returns nothing.
        """
        self.text = text
        self.day_index = day_index

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

    def day(self, segment, now):
        """The trading day this copy goes on.

        Args:
            segment (str): The instrument's exchange-prefixed segment, whose calendar is followed.
            now (datetime.datetime): The moment the plan is placed, in India's time.

        Returns:
            datetime.date: The day.
        """
        wanted = datetime.time.fromisoformat(self.text)
        trading_days = TradingDays()
        day = now.date()
        if not trading_days.is_trading_day(segment, day) or now.time() >= wanted:
            day = trading_days.next_trading_day(segment, day)
        for _ in range(self.day_index):
            day = trading_days.next_trading_day(segment, day)
        return day

    def prepare(self, plan_order, memory):
        """Works out the moment this copy's time falls on, and keeps it in the condition's memory.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which knows its instrument's segment.
            memory (dict): The condition's memory, given `at`, the Unix time.

        Returns:
            None: This method returns nothing.
        """
        now = moments.Moments().now()
        day = self.day(plan_order.trading_segment(), now)
        moment = datetime.datetime.combine(day, datetime.time.fromisoformat(self.text), moments.INDIA)
        memory['at'] = moment.timestamp()

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether this copy's moment has come.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): The condition's memory, holding `at`.
            quotes (dict): Unused.
            now (float): The Unix time of the tick.
            opening_side (str): Unused.
            sending_side (str): Unused.

        Returns:
            bool: True from the moment on.
        """
        del plan_order, quotes, opening_side, sending_side
        moment = memory.get('at')
        if moment is None:
            return False
        return now >= moment

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The time and the trading day.
        """
        return {
            'trading_day_at': {
                'time': self.text,
                'day_index': self.day_index,
            },
        }
