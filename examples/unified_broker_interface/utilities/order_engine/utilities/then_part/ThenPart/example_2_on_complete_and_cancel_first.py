"""Shows a Then join that waits for its first plan to finish, and one whose child filling cancels the rest of the first plan.

With `on_complete`, a `ThenPart`'s child waits until the first plan is done, and is sized to everything it filled; a first plan that finishes without filling anything cancels the child without ever placing it. With `cancel_first_on_child_fill`, as in a bracket, a fill on the child cancels whatever of the first plan is still working, because an entry that keeps buying while its exit is selling only grows an unprotected position. `set_target` passes a size down to the first plan, and `cancel_rest` stops the whole branch.

A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/then_part/ThenPart/example_2_on_complete_and_cancel_first.py
"""

import copy
import decimal

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
from unified_broker_interface.utilities.order_engine.utilities.then_part import (
    ThenPart,
)


class StandInPlanOrder:
    """Stands in for the plan order: keeps the parts' records in the parent's parameters, and turns every order placed into a leg the broker has acknowledged, noting each request.

    A cancel is treated as confirmed at once, and a fill is written onto a leg by `fill`, so a program can walk parts through what a broker would report without any broker.

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
        self.requests.append(('place', role, leg.transaction_type, leg.quantity, order.get('order_type'), leg.price))
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
        self.requests.append(('change', leg.role, quantity))
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
        self.requests.append(('cancel', leg.role))
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


class PartMaker:
    """Builds the order parts the programs join."""

    def entry(self, path):
        """The caller's own order, with its tag.

        Args:
            path (str): The part's path.

        Returns:
            OrderPart: The part.
        """
        return OrderPart(path, [], None, None, FixedPricing(None, None), True)

    def stop(self, path):
        """A stop-limit protecting the position, triggering at 990 with a limit of 988.

        Args:
            path (str): The part's path.

        Returns:
            OrderPart: The part.
        """
        return OrderPart(path, [], None, 'protect', NativeStopPricing(decimal.Decimal('990'), decimal.Decimal('988')), False)

    def target(self, path):
        """A limit at 1,010 protecting the position.

        Args:
            path (str): The part's path.

        Returns:
            OrderPart: The part.
        """
        return OrderPart(path, [], None, 'protect', FixedPricing(decimal.Decimal('1010'), None), False)


class OnCompleteAndCancelFirstExample:
    """Runs three Then joins and prints what each did."""

    def fresh(self, child_key, cancel_first):
        """A new stand-in and a join of an entry and a target.

        Args:
            child_key (str): `each_fill` or `on_complete`.
            cancel_first (bool): Whether a fill on the child cancels the rest of the entry.

        Returns:
            tuple: The stand-in plan order (StandInPlanOrder) and the join (ThenPart).
        """
        plan_order = StandInPlanOrder()
        parts = PartMaker()
        join = ThenPart('root', parts.entry('root.first'), parts.target(f'root.{child_key}'), child_key, cancel_first)
        for part in join.order_parts():
            plan_order.set_part_record(part.path, {'state': 'pending'}, None)
        join.start(plan_order, None, None, {})
        return plan_order, join

    def run(self):
        """Runs the three joins.

        Returns:
            None: This method returns nothing.
        """
        plan_order, join = self.fresh('on_complete', False)
        plan_order.fill('root.first', 6)
        join.settle(plan_order)
        print(f'on_complete, entry 6 of 10: child started {join.child.is_started(plan_order)}')
        plan_order.fill('root.first', 10)
        join.settle(plan_order)
        join.settle(plan_order)
        print(f'on_complete, entry done: requests {plan_order.requests[1:]}')

        plan_order, join = self.fresh('on_complete', False)
        join.set_target(plan_order, 5)
        join.cancel_rest(plan_order, 'the caller changed their mind')
        join.settle(plan_order)
        join.settle(plan_order)
        print(f'on_complete, cancelled unfilled: requests {plan_order.requests[1:]}, done {join.is_done(plan_order)}')

        plan_order, join = self.fresh('each_fill', True)
        plan_order.fill('root.first', 4)
        join.settle(plan_order)
        plan_order.fill('root.each_fill', 2)
        join.settle(plan_order)
        print(f'cancel_first_on_child_fill: requests {plan_order.requests[1:]}')
        print(f'Messages: {plan_order.messages}')


if __name__ == '__main__':
    OnCompleteAndCancelFirstExample().run()
