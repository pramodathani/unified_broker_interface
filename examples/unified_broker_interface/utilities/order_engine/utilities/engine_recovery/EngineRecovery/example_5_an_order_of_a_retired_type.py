"""Warns about an open order recorded under a type the engine no longer runs, naming the broker orders left to look after by hand.

Every named order type now runs as a plan, so a parent recorded before that, under a name such as `bracket`, has no class to run it: recovery still rebuilds and reconciles it, but nothing would react to its fills or ticks, and it cannot be changed or cancelled by its parent id. `EngineRecovery.warn_if_unrun` logs a warning for such a parent while it is open, listing its broker orders that have not finished, and says nothing about a plan or a simple order. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_recovery/EngineRecovery/example_5_an_order_of_a_retired_type.py
"""

from unified_broker_interface.utilities.order_engine.utilities.engine_recovery import (
    EngineRecovery,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)


class PrintingLogger:
    """Stands in for the engine's logger, printing each warning."""

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The warning.

        Returns:
            None: This method returns nothing.
        """
        print(f'WARNING {message}')


class AnOrderOfARetiredTypeExample:
    """Asks recovery about an open bracket recorded before the switch to plans, and about an open plan."""

    def leg(self, leg_id, role, broker_order_id, state):
        """A leg at Zerodha.

        Args:
            leg_id (str): The leg's id.
            role (str): The leg's role.
            broker_order_id (str): Zerodha's order id.
            state (str): The leg's state.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg(leg_id, role)
        leg.broker = 'zerodha'
        leg.broker_order_id = broker_order_id
        leg.state = state
        return leg

    def run(self):
        """Prints what recovery says about each parent.

        Returns:
            None: This method returns nothing.
        """
        recovery = EngineRecovery(None, None, None, ['zerodha'], PrintingLogger())
        bracket = ParentOrder('bracket-from-friday')
        bracket.synthetic_type = 'bracket'
        bracket.state = 'protecting'
        bracket.legs.append(self.leg('bracket-from-friday:1', 'entry', '2610030000000001', 'filled'))
        bracket.legs.append(self.leg('bracket-from-friday:2', 'stop', '2610030000000002', 'acknowledged'))
        bracket.legs.append(self.leg('bracket-from-friday:3', 'target', '2610030000000003', 'acknowledged'))
        plan = ParentOrder('plan-from-today')
        plan.synthetic_type = 'plan'
        plan.state = 'working'
        print('The bracket:')
        recovery.warn_if_unrun(bracket)
        print('The plan:')
        recovery.warn_if_unrun(plan)
        print('(nothing to say)')


if __name__ == '__main__':
    AnOrderOfARetiredTypeExample().run()
