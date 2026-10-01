"""Shows that an order part places its orders under its own path and only ever looks at the broker orders it placed itself.

Every broker order an `OrderPart` places carries the part's path as its role, and the part only looks at orders with that role. This is the rule that lets parts share one parent: today's order types each assume they own every leg, so a second type's leg would confuse them. This program builds a parent holding a filled order for the part `root` and a resting order for another part, `root.first`, and shows that `root` is done while `root.first` is not.

It then starts a part through a small stand-in for the plan order, which records the role each broker order is placed with instead of sending it, and prints the part as a dry run would show it, from `expanded`.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_2_sees_only_its_own_legs.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.order_part import (
    OrderPart,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)


class StandInPlanOrder:
    """Stands in for the plan order a part is started through, recording each order instead of sending it.

    Attributes:
        parent (ParentOrder): The parent, whose body is the caller's order.
        placed (list): Each order placed, as `(role, broker)`.
    """

    def __init__(self):
        """Builds the stand-in with a body that names no broker.

        Returns:
            None: This method returns nothing.
        """
        self.parent = ParentOrder('parent-2')
        self.parent.body = {
            'transaction_type': 'BUY',
            'quantity': 10,
        }
        self.placed = []

    def read_order(self, body):
        """Answers with the body itself, standing in for a validated order.

        Args:
            body (dict): The body.

        Returns:
            dict: The same body.
        """
        return body

    def concrete_order(self, order):
        """Answers with the order itself, since it names no references.

        Args:
            order (dict): The order.

        Returns:
            dict: The same order.
        """
        return order

    def place_leg(self, role, order, started_at, broker_name):
        """Records the role and broker an order is placed with, and answers that it was accepted.

        Args:
            role (str): The leg's role, which a part sets to its path.
            order (dict): The order.
            started_at (float | None): Unused.
            broker_name (str | None): The broker the body names, or None.

        Returns:
            tuple: The answer (dict), its HTTP status (int) and the leg (None here).
        """
        del order, started_at
        self.placed.append((role, broker_name))
        return {
            'outcome': 'accepted',
        }, 200, None


class SeesOnlyItsOwnLegsExample:
    """Builds a parent shared by two parts and prints what each part sees.

    Attributes:
        parent (ParentOrder): The shared parent.
    """

    def __init__(self):
        """Builds the parent with one filled leg for `root` and one resting leg for `root.first`.

        Returns:
            None: This method returns nothing.
        """
        self.parent = ParentOrder('parent-1')
        filled = OrderLeg('parent-1:1', 'root')
        filled.state = 'filled'
        filled.quantity = 10
        filled.filled_quantity = 10
        resting = OrderLeg('parent-1:2', 'root.first')
        resting.state = 'acknowledged'
        resting.quantity = 5
        self.parent.legs.append(filled)
        self.parent.legs.append(resting)

    def show(self, path):
        """Prints the legs one part sees and whether it is done.

        Args:
            path (str): The part's path.

        Returns:
            None: This method returns nothing.
        """
        part = OrderPart(
            path,
            [
                'simple',
            ],
        )
        own = []
        for leg in part.own_legs(self.parent):
            own.append(leg.leg_id)
        print(f'{path}: sees {own}, done reason {part.done_reason(self.parent)}')

    def run(self):
        """Prints what both parts see.

        Returns:
            None: This method returns nothing.
        """
        print(f'The parent holds {len(self.parent.legs)} legs')
        self.show('root')
        self.show('root.first')
        plan_order = StandInPlanOrder()
        part = OrderPart(
            'root',
            [
                'simple',
            ],
        )
        body, status = part.start(plan_order, None)
        print(f"Started root: HTTP {status}, {body['outcome']}, placed as {plan_order.placed}")
        print(f'As a dry run shows it: {part.expanded()}')


if __name__ == '__main__':
    SeesOnlyItsOwnLegsExample().run()
