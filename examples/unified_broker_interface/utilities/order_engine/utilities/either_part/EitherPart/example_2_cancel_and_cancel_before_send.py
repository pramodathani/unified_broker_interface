"""Shows an Either join that cancels: once one child fills, the others are stopped, and a child can clear its siblings before it is sent.

An `EitherPart` with `sibling_rule` `cancel` suits children that are different trades. Once any child has filled something, every other child is cancelled: a resting one at the broker, and one still waiting on a trigger simply marked done. `cancel_siblings` is also what the plan order calls for a join with `cancel_before_send`, before it sends a child whose trigger held, which is how a hidden stop removes its native backstop before its own exit goes out. `cancel_rest` stops every child, and `is_started` says whether any has begun.

A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/either_part/EitherPart/example_2_cancel_and_cancel_before_send.py
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


class CancelAndCancelBeforeSendExample:
    """Runs two cancel joins and prints what each did."""

    def fresh(self):
        """A new stand-in and a cancel join of a stop and a target, with cancel before send.

        Returns:
            tuple: The stand-in plan order (StandInPlanOrder) and the join (EitherPart).
        """
        plan_order = StandInPlanOrder()
        parts = PartMaker()
        join = EitherPart('root', [parts.stop('root.children.0'), parts.target('root.children.1')], 'cancel', True)
        for part in join.order_parts():
            plan_order.set_part_record(part.path, {'state': 'pending'}, None)
        print(f'Started before anything: {join.is_started(plan_order)}')
        join.start(plan_order, None, None, {})
        return plan_order, join

    def run(self):
        """Runs the two joins.

        Returns:
            None: This method returns nothing.
        """
        plan_order, join = self.fresh()
        plan_order.fill('root.children.1', 4)
        join.settle(plan_order)
        join.settle(plan_order)
        print(f'Target filled 4: requests {plan_order.requests[2:]}, stop record {plan_order.part_record("root.children.0")}')

        plan_order, join = self.fresh()
        cleared = join.cancel_siblings(plan_order, 0, 'the stop is about to be sent')
        print(f"Clearing the stop's siblings: {cleared}, requests {plan_order.requests[2:]}")
        stopped = join.cancel_rest(plan_order, 'the caller cancelled the plan')
        join.settle(plan_order)
        print(f'Stopping everything: {stopped}, requests {plan_order.requests[2:]}, done {join.is_done(plan_order)}')


if __name__ == '__main__':
    CancelAndCancelBeforeSendExample().run()
