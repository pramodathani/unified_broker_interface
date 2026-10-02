"""Shows a caller cutting one exit of a bracket, and the other exit following it, because an Either join that reduces counts the cut against the quantity both share.

A bracket protects ten shares with a stop and a target, joined by an `EitherPart` whose `sibling_rule` is `reduce`. The caller cuts the stop's broker order from ten to six through `PUT /api/orders/modify`. The stop is sent all at once, so its quantity is the caller's to set, and since it sits under a join that reduces, the plan order hands the cut to `EitherPart.take_caller_change` rather than to the stop alone. `budget` drops from ten to six, and the next `settle` brings the target down to six as well, so neither exit covers more than the other. When the target then fills two, the stop comes down to four, from the new budget of six rather than the old ten.

A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/either_part/EitherPart/example_3_a_callers_change.py
"""

import copy
import decimal

from unified_broker_interface.utilities.order_engine.utilities.either_part import (
    EitherPart,
)
from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.native_stop_pricing import (
    NativeStopPricing,
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


class StandInPlanOrder:
    """Stands in for the plan order: keeps the parts' records in the parent's parameters, and turns every order placed into a leg the broker has acknowledged, noting each request.

    A cancel is treated as confirmed at once, a fill is written onto a leg by `fill`, and a caller's change is written onto a leg by `caller_changes`, so a program can walk parts through what a broker would report without any broker.

    Attributes:
        parent (ParentOrder): The parent, holding the caller's buy of ten RELIANCE at 1,000 and the legs placed.
        requests (list): Every request, as a tuple naming what was asked.
        messages (list): Every change of a part's record that would be recorded as an event.
    """

    def __init__(self):
        """Builds the stand-in with nothing placed.

        Returns:
            None: This method returns nothing.
        """
        self.parent = ParentOrder('parent-1')
        self.parent.body = {
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 10,
            'price': '1000.00',
        }
        self.parent.parameters = {
            'parts': {},
        }
        self.requests = []
        self.messages = []

    def part_record(self, path):
        """A copy of one part's record.

        Args:
            path (str): The part's path.

        Returns:
            dict: The record, empty when the part has none.
        """
        return copy.deepcopy(self.parent.parameters['parts'].get(path) or {})

    def set_part_record(self, path, record, message):
        """Keeps one part's record, and notes the message an event would carry.

        Args:
            path (str): The part's path.
            record (dict): The record.
            message (str | None): The event's message, or None when no event would be recorded.

        Returns:
            None: This method returns nothing.
        """
        self.parent.parameters['parts'][path] = record
        if message is not None:
            self.messages.append(message)

    def quotes_now(self):
        """The quotes now, which are none, since nothing here is priced from the book.

        Returns:
            dict: An empty dictionary.
        """
        return {}

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

    def chosen_broker(self):
        """The broker every order goes to here.

        Returns:
            str: `zerodha`.
        """
        return 'zerodha'

    def place_leg(self, role, order, started_at, broker_name):
        """Adds the order to the parent as an acknowledged leg.

        Args:
            role (str): The leg's role, the part's path.
            order (dict): The order.
            started_at (float | None): Unused.
            broker_name (str | None): Unused.

        Returns:
            tuple: The answer (dict), its HTTP status (int) and the leg (OrderLeg).
        """
        del started_at, broker_name
        number = len(self.parent.legs) + 1
        leg = OrderLeg(f'parent-1:{number}', role)
        leg.state = 'acknowledged'
        leg.broker_order_id = str(number)
        leg.transaction_type = order['transaction_type']
        leg.quantity = order['quantity']
        leg.price = order.get('price')
        self.parent.legs.append(leg)
        self.requests.append((
            'place',
            role,
            leg.transaction_type,
            leg.quantity,
            order.get('order_type'),
            leg.price,
        ))
        return {
            'outcome': 'accepted',
            'order_id': leg.broker_order_id,
            'broker': 'zerodha',
        }, 200, leg

    def reduce_leg(self, leg, quantity, reason):
        """Changes a leg's quantity, as the broker would once it accepts the change.

        Args:
            leg (OrderLeg): The leg.
            quantity (int): Its new total quantity.
            reason (str): Unused.

        Returns:
            bool: True, since the change is accepted.
        """
        del reason
        self.requests.append((
            'change',
            leg.role,
            quantity,
        ))
        leg.quantity = quantity
        return True

    def cancel_leg(self, leg, reason):
        """Cancels a leg, as the broker would once it confirms the cancel.

        Args:
            leg (OrderLeg): The leg.
            reason (str): Unused.

        Returns:
            bool: True, since the cancel is accepted.
        """
        del reason
        self.requests.append((
            'cancel',
            leg.role,
        ))
        leg.state = 'cancelled'
        return True

    def fill(self, role, filled):
        """Writes a fill onto the live leg of one part, as an order update would.

        Args:
            role (str): The part's path.
            filled (int): The leg's filled quantity so far.

        Returns:
            None: This method returns nothing.
        """
        for leg in self.parent.legs:
            if leg.role == role and not leg.is_finished():
                leg.filled_quantity = filled
                if filled >= leg.quantity:
                    leg.state = 'filled'
                return

    def caller_changes(self, role, quantity):
        """Writes a caller's new quantity onto the live leg of one part, as the broker's answer to `PUT /api/orders/modify` would.

        Args:
            role (str): The part's path.
            quantity (int): The leg's new quantity.

        Returns:
            int: How much the caller added, negative for a cut.
        """
        for leg in self.parent.legs:
            if leg.role == role and not leg.is_finished():
                change = quantity - leg.quantity
                leg.quantity = quantity
                return change
        return 0

    def resting_quantities(self):
        """The quantity of every leg still resting, by its part's path.

        Returns:
            dict: Each part's path mapped to its resting leg's quantity.
        """
        quantities = {}
        for leg in self.parent.legs:
            if not leg.is_finished():
                quantities[leg.role] = leg.quantity
        return quantities


class PartMaker:
    """Builds the order parts the programs join."""

    def stop(self, path):
        """A stop-limit protecting the position, triggering at 990 with a limit of 988.

        Args:
            path (str): The part's path.

        Returns:
            OrderPart: The part.
        """
        return OrderPart(
            path,
            [],
            None,
            'protect',
            NativeStopPricing(decimal.Decimal('990'), decimal.Decimal('988')),
            False,
        )

    def target(self, path):
        """A limit at 1,010 protecting the position.

        Args:
            path (str): The part's path.

        Returns:
            OrderPart: The part.
        """
        return OrderPart(
            path,
            [],
            None,
            'protect',
            FixedPricing(decimal.Decimal('1010'), None),
            False,
        )


class ACallersChangeExample:
    """Cuts a bracket's stop and prints the target following it.

    Attributes:
        plan_order (StandInPlanOrder): The stand-in plan order.
        stop (OrderPart): The bracket's stop.
        target (OrderPart): The bracket's target.
        join (EitherPart): The join that reduces, holding the stop and the target.
    """

    def __init__(self):
        """Builds the bracket.

        Returns:
            None: This method returns nothing.
        """
        self.plan_order = StandInPlanOrder()
        parts = PartMaker()
        self.stop = parts.stop('root.children.0')
        self.target = parts.target('root.children.1')
        children = [
            self.stop,
            self.target,
        ]
        self.join = EitherPart('root', children, 'reduce', False)

    def run(self):
        """Starts the bracket, cuts the stop, settles, fills the target two and settles again.

        Returns:
            None: This method returns nothing.
        """
        pending = {
            'state': 'pending',
        }
        for part in self.join.order_parts():
            self.plan_order.set_part_record(part.path, copy.deepcopy(pending), None)
        self.join.start(self.plan_order, None, None, {})
        print(f'Budget {self.join.budget(self.plan_order)}; resting {self.plan_order.resting_quantities()}')
        change = self.plan_order.caller_changes(self.stop.path, 6)
        print(f"The caller cut the stop to 6, a change of {change}; the stop keeps the caller's quantity: {self.stop.keeps_caller_quantity()}")
        count = len(self.plan_order.messages)
        self.join.take_caller_change(self.plan_order, change)
        print(f"Budget {self.join.budget(self.plan_order)}; the join's record {self.plan_order.part_record(self.join.path)}")
        self.join.settle(self.plan_order)
        print(f'Settled: requests {self.plan_order.requests[2:]}, resting {self.plan_order.resting_quantities()}')
        self.plan_order.fill(self.target.path, 2)
        self.join.settle(self.plan_order)
        print(f'Target filled 2 and settled: requests {self.plan_order.requests[2:]}, resting {self.plan_order.resting_quantities()}')
        print(f'Messages: {self.plan_order.messages[count:]}')


if __name__ == '__main__':
    ACallersChangeExample().run()
