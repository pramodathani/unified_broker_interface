"""The trigger condition that holds once a number of minutes have passed since the plan was placed."""

from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)


class ElapsedCondition:
    """A plan order's trigger condition that holds once `minutes` have passed since the plan was placed.

    It is what spaces a Repeat join's copies: the copy sent third of an accumulation every thirty minutes waits for sixty. The moment is worked out when the plan is placed and kept in the condition's memory, so a restart keeps the schedule, and it needs no prices, so clock ticks fire it.

    Attributes:
        minutes (float): How long after placing it holds.
    """

    def __init__(self, minutes):
        """Builds the condition.

        Args:
            minutes (float): How long after placing it holds.

        Returns:
            None: This method returns nothing.
        """
        self.minutes = minutes

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
        """Works out the moment it holds from, and keeps it in the condition's memory.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): The condition's memory, given `at`, the Unix time.

        Returns:
            None: This method returns nothing.
        """
        del plan_order
        memory['at'] = Moments().now().timestamp() + self.minutes * 60

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the time has come.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): The condition's memory, holding `at`.
            quotes (dict): Unused.
            now (float): The Unix time of the tick.
            opening_side (str): Unused.
            sending_side (str): Unused.

        Returns:
            bool: True once the moment has passed.
        """
        del plan_order, quotes, opening_side, sending_side
        moment = memory.get('at')
        if moment is None:
            return False
        return now >= moment

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The minutes.
        """
        return {
            'elapsed': {
                'minutes': self.minutes,
            },
        }
