"""The execution that sends an order again each trading morning, for an order that has to be renewed because the exchange ends it at the close."""

import datetime

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)


class DailyExecution:
    """A plan order's execution that, each trading day at `arm_at`, sends the order again for whatever has not traded.

    It keeps the schedule of today's daily stop. A native stop dies at the close, so a position held for a week needs a new one every morning; this sends it at `arm_at`, 09:20 by default, after the pre-open has settled, and not on a day the instrument does not trade. A plan placed after that time on a trading day, or on a day that does not trade, first sends on the next trading morning. Once anything has traded, the position has been closed and no more is sent. The day last sent on is kept in memory and recorded with the order, so a restart does not send twice on one day. A lifetime of days ends it.

    Attributes:
        arm_at (str): The time of day, `HH:MM`, to send at.
    """

    def __init__(self, arm_at):
        """Builds the execution from a time the plan reader has already checked.

        Args:
            arm_at (str): The time of day, `HH:MM`.

        Returns:
            None: This method returns nothing.
        """
        self.arm_at = arm_at

    def needs_prices(self):
        """Whether this execution reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def paced_by_ticks(self):
        """Whether this execution sends on later ticks, which it does, each morning.

        Returns:
            bool: True.
        """
        return True

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing a resting order, which it is not.

        Returns:
            bool: False.
        """
        return False

    def arm_moment(self, day):
        """The moment `arm_at` falls on a day, in India.

        Args:
            day (datetime.date): The day.

        Returns:
            datetime.datetime: The moment.
        """
        hours, _, minutes = self.arm_at.partition(':')
        return datetime.datetime.combine(day, datetime.time(int(hours), int(minutes)), moments.INDIA)

    def begin(self, plan_order, memory, quotes, now):
        """Keeps the instrument's calendar, and counts today as done when its time has passed or it does not trade.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which names its segment.
            memory (dict): The execution's memory, given `segment` and `armed_on`.
            quotes (dict): Unused.
            now (float): The Unix time the order started working.

        Returns:
            None: This method returns nothing.
        """
        del quotes
        segment = plan_order.trading_segment()
        memory['segment'] = segment
        when = datetime.datetime.fromtimestamp(now, moments.INDIA)
        armed_on = None
        if not TradingDays().is_trading_day(segment, when.date()) or when >= self.arm_moment(when.date()):
            armed_on = when.date().isoformat()
        memory['armed_on'] = armed_on

    def traded(self, pieces):
        """How much the orders sent so far have filled.

        Args:
            pieces (list): The broker orders sent so far.

        Returns:
            int: The quantity.
        """
        total = 0
        for piece in pieces:
            total = total + (piece.filled_quantity or 0)
        return total

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now, sending_side=None):
        """Today's order, once its time has come on a trading day it has not yet been sent on.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): The execution's memory, whose `armed_on` moves on when an order is due.
            total (int): The quantity the order should trade.
            pieces (list): The broker orders sent so far.
            quotes (dict): Unused.
            now (float): The Unix time of the tick.
            sending_side (str | None): Unused.

        Returns:
            list: One quantity, or nothing.
        """
        del plan_order, quotes, sending_side
        if not self.will_send_more(memory, total - self.traded(pieces), pieces):
            return []
        when = datetime.datetime.fromtimestamp(now, moments.INDIA)
        today = when.date()
        if memory.get('armed_on') == today.isoformat():
            return []
        segment = memory.get('segment')
        if segment and not TradingDays().is_trading_day(segment, today):
            return []
        if when < self.arm_moment(today):
            return []
        memory['armed_on'] = today.isoformat()
        return [
            total,
        ]

    def will_send_more(self, memory, remaining, pieces):
        """Whether more mornings may still send, which they may until anything has traded.

        Args:
            memory (dict): Unused.
            remaining (int): Unused.
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True while nothing has traded.
        """
        del memory, remaining
        return self.traded(pieces) == 0

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The time of day.
        """
        return {
            'daily': {
                'arm_at': self.arm_at,
            },
        }
