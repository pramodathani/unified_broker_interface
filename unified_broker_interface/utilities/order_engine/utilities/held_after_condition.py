"""The trigger condition that waits for an order's own trigger to fire once, and then holds the order until its limit would fill straight away."""

from unified_broker_interface.utilities.order_engine.utilities.limit_marketable_condition import (
    LimitMarketableCondition,
)


class HeldAfterCondition(LimitMarketableCondition):
    """A plan order's trigger that keeps the order's own trigger and adds holding after it.

    An order asked to be held in the virtual order book may already wait for something, such as a time of day or a price touching a level. Without holding it would be sent the moment that trigger fires and then rest at the broker. Held, it is sent at the same moment only if the other side of the book has reached its limit, and otherwise waits in the engine until it does. Most triggers hold only while their condition is true on the current tick, so a price that touches a level and moves away again would leave a plain `all` of the two never true together. This condition remembers that the order's own trigger has fired, and from then on it is the `limit_marketable` condition alone.

    The held terms the virtual book reads are written when the trigger fires rather than when the plan is placed, so the queue estimate starts when a resting order would have started queuing.

    Attributes:
        first (object): The order's own trigger, a condition object or a `ConditionGroup`.
    """

    def __init__(self, first):
        """Builds the condition around the order's own trigger.

        Args:
            first (object): The order's own trigger.

        Returns:
            None: This method returns nothing.
        """
        self.first = first

    def needs_prices(self):
        """Whether this condition reads quotes, which it does once the trigger has fired.

        Returns:
            bool: True.
        """
        return True

    def instruments(self):
        """The instruments other than the order's own that the order's own trigger watches.

        Returns:
            list: The instrument ids.
        """
        return self.first.instruments()

    def _first_memory(self, memory):
        """The order's own trigger's memory, inside this condition's.

        Args:
            memory (dict): This condition's memory, changed in place when the trigger has none yet.

        Returns:
            dict: The trigger's memory.
        """
        if 'first' not in memory:
            memory['first'] = {}
        return memory['first']

    def prepare(self, plan_order, memory):
        """Readies the order's own trigger, and checks the order is a limit order that can be held, when the plan is placed.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): This condition's memory, changed in place.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: When the order's own trigger cannot be readied, or with HTTP 400 when the order is not a LIMIT order with a price.
        """
        self.first.prepare(plan_order, self._first_memory(memory))
        self.limit_price(plan_order)

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the order's own trigger has fired, now or before, and the other side of the book has reached the limit price.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): This condition's memory, changed in place.
            quotes (dict): The quotes the tick carried, by instrument id.
            now (float): The Unix time of the tick.
            opening_side (str): BUY or SELL, the side the caller's order was opened with.
            sending_side (str): BUY or SELL, the side the order will be sent on.

        Returns:
            bool: True when the order is to be sent now.
        """
        if memory.get('fired') is not True:
            fired = self.first.is_met(
                plan_order,
                self._first_memory(memory),
                quotes,
                now,
                opening_side,
                sending_side,
            )
            if not fired:
                return False
            memory['fired'] = True
            super().prepare(plan_order, memory)
        return super().is_met(plan_order, memory, quotes, now, opening_side, sending_side)

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The order's own trigger, held after.
        """
        return {
            'held_after': self.first.described(),
        }
