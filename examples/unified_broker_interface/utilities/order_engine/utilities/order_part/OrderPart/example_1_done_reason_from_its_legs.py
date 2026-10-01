"""Shows when an order part counts as done, and why, from the state of its broker orders.

An `OrderPart` is one order in a plan. It is done once every broker order it placed has finished, and the reason is `filled`, `partly_filled`, `refused` or `cancelled`. This program builds a parent holding one broker order for the part `root` and prints the part's reason as that order moves through the states a broker reports.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_1_done_reason_from_its_legs.py
"""

from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.order_part import (
    OrderPart,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)


class DoneReasonFromItsLegsExample:
    """Prints an order part's done reason for each state its broker order can reach.

    Attributes:
        part (OrderPart): The part.
    """

    def __init__(self):
        """Builds the part for the plan's root order.

        Returns:
            None: This method returns nothing.
        """
        self.part = OrderPart(
            'root',
            [
                'simple',
            ],
            None,
            None,
            FixedPricing(None, None),
        )

    def reason(self, state, filled):
        """The part's done reason when its one broker order is in a state.

        Args:
            state (str): The broker order's state.
            filled (int): How much of its 10 has filled.

        Returns:
            str | None: The reason.
        """
        parent = ParentOrder('parent-1')
        leg = OrderLeg('parent-1:1', 'root')
        leg.state = state
        leg.quantity = 10
        leg.filled_quantity = filled
        parent.legs.append(leg)
        return self.part.done_reason(parent)

    def run(self):
        """Prints the reason for each state.

        Returns:
            None: This method returns nothing.
        """
        print(f"Resting, nothing filled: {self.reason('acknowledged', 0)}")
        print(f"Resting, 4 of 10 filled: {self.reason('acknowledged', 4)}")
        print(f"Filled: {self.reason('filled', 10)}")
        print(f"Cancelled after 4 filled: {self.reason('cancelled', 4)}")
        print(f"Cancelled with nothing filled: {self.reason('cancelled', 0)}")
        print(f"Rejected by the broker: {self.reason('rejected', 0)}")
        print(f"Outcome unknown: {self.reason('unknown', 0)}")


if __name__ == '__main__':
    DoneReasonFromItsLegsExample().run()
