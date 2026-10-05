"""Walks one order part through the lifecycle a join drives: start, a fill, a new target, cancelling the rest, and done.

An `OrderPart` placed under a join is told how much to trade with a target. `start` places it for that much, `traded` says what has filled, `total` is how much it should trade in all and `committed` how much its broker orders account for, `send_due` sends whatever its execution says is due, which for an order sent all at once is nothing once it has gone, `set_target` changes its resting order to the filled part plus what is still wanted, or cancels it when nothing more is wanted, `cancel_rest` stops whatever is left, asking each broker order's cancel through `cancel_once`, which never asks twice for an order whose cancel the broker has accepted, and `settle` marks it done once every broker order has finished. `send` is how a part left waiting, for its trigger or for a price, is placed when its tick comes, and `move` is how a working trailing stop follows the market on a tick. A part that has not been started yet only records a new target. This program also shows how the part describes its quantity, what it holds as a member of a tree, and that an ordinary order readies no memory of its own when the plan is placed.

A stand-in plays the plan order: it keeps the parts' records and turns every order into an acknowledged leg, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_3_lifecycle_under_a_join.py
"""

import copy
import decimal

from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
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
from unified_broker_interface.utilities.order_engine.utilities.trail_pricing import (
    TrailPricing,
)


class StandInPlanOrder:
    """Stands in for the plan order: keeps the parts' records in the parent's parameters, and turns every order placed into a leg the broker has acknowledged, noting each request.

    A cancel is treated as confirmed at once, and a fill is written onto a leg by `fill`, so a program can walk parts through what a broker would report without any broker.

    Attributes:
        parent (ParentOrder): The parent, holding the caller's buy of ten RELIANCE at 1,000 and the legs placed.
        requests (list): Every request, as a tuple naming what was asked.
        messages (list): Every change of a part's record that would be recorded as an event.
        group_margin_legs (OrderLegs | None): The group a Together join hands the broker selector, which is none here.
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
        self.group_margin_legs = None

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
        leg.trigger_price = order.get('trigger_price')
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

    def view(self, quotes, instrument_id=None):
        """A quote as a market view, with RELIANCE's tick size of 0.05.

        Args:
            quotes (dict): Quotes by instrument id.
            instrument_id (str | None): Unused, since there is one instrument.

        Returns:
            MarketView: The view.
        """
        del instrument_id
        return MarketView(quotes.get('reliance'), decimal.Decimal('0.05'))

    def tick_size(self):
        """RELIANCE's tick size.

        Returns:
            decimal.Decimal: 0.05.
        """
        return decimal.Decimal('0.05')

    def reprice_leg(self, leg, price, trigger_price, reason):
        """Moves a leg's prices, as the broker would once it accepts the change.

        Args:
            leg (OrderLeg): The leg.
            price (decimal.Decimal): Its new limit price.
            trigger_price (decimal.Decimal): Its new trigger price.
            reason (str): Unused.

        Returns:
            bool: True, since the change is accepted.
        """
        del reason
        self.requests.append(('move', leg.role, str(trigger_price), str(price)))
        leg.trigger_price = trigger_price
        leg.price = price
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
        """A stop-limit protecting the position, triggering at 990 with a limit of 988, sharing its quantity with its sibling as a reduce join's child does, which the plan reader marks.

        Args:
            path (str): The part's path.

        Returns:
            OrderPart: The part.
        """
        part = OrderPart(path, [], None, 'protect', NativeStopPricing(decimal.Decimal('990'), decimal.Decimal('988')), False)
        part.shares_quantity = True
        return part

    def target(self, path):
        """A limit at 1,010 protecting the position, sharing its quantity with its sibling as a reduce join's child does, which the plan reader marks.

        Args:
            path (str): The part's path.

        Returns:
            OrderPart: The part.
        """
        part = OrderPart(path, [], None, 'protect', FixedPricing(decimal.Decimal('1010'), None), False)
        part.shares_quantity = True
        return part


class LifecycleUnderAJoinExample:
    """Drives a stop through its lifecycle.

    Attributes:
        plan_order (StandInPlanOrder): The stand-in plan order.
        part (OrderPart): The stop.
    """

    def __init__(self):
        """Builds the stand-in and the stop.

        Returns:
            None: This method returns nothing.
        """
        self.plan_order = StandInPlanOrder()
        self.part = PartMaker().stop('root.each_fill')

    def run(self):
        """Prints each step.

        Returns:
            None: This method returns nothing.
        """
        print(f'Orders {[part.path for part in self.part.order_parts()]}, members {self.part.members()}, standalone protecting {len(self.part.standalone_protecting_parts())}')
        print(f'Memory readied when the plan is placed, which only a part kept whole has: {self.part.prepared_own_memory(self.plan_order)}')
        entry = PartMaker().entry('root.first')
        print(f"Quantity: {self.part.quantity_described()}; the entry's: {entry.quantity_described()}")
        self.plan_order.set_part_record(self.part.path, {'state': 'pending'}, None)
        self.part.set_target(self.plan_order, 4)
        print(f'Before starting, a target of 4 is only recorded: {self.plan_order.part_record(self.part.path)}, started {self.part.is_started(self.plan_order)}')
        placed = self.part.start(self.plan_order, 4, None, {})
        print(f'Started: {placed}')
        self.plan_order.fill(self.part.path, 1)
        self.part.set_target(self.plan_order, 10)
        print(f'1 filled, target 10: traded {self.part.traded(self.plan_order.parent)}, total {self.part.total(self.plan_order)}, committed {self.part.committed(self.plan_order.parent)}, requests {self.plan_order.requests[1:]}')
        print(f'Due now, with its one order resting: {self.part.send_due(self.plan_order, None, {}, 0.0)}')
        self.part.set_target(self.plan_order, 1)
        print(f'Target 1: requests {self.plan_order.requests[1:]}')
        self.part.settle(self.plan_order)
        print(f'Settled: done {self.part.is_done(self.plan_order)}, record {self.plan_order.part_record(self.part.path)}')
        again = PartMaker().target('root.children.1')
        self.plan_order.set_part_record(again.path, {'state': 'pending'}, None)
        again.start(self.plan_order, 5, None, {})
        again.cancel_rest(self.plan_order, 'its sibling filled')
        cancels = len(self.plan_order.requests)
        asked_again = again.cancel_once(self.plan_order, self.plan_order.parent.legs[-1], 'its sibling filled')
        print(f'Asked to cancel again before settling: {asked_again}, with {len(self.plan_order.requests) - cancels} more requests')
        again.settle(self.plan_order)
        print(f'A target cancelled and settled: done {again.is_done(self.plan_order)}, record {self.plan_order.part_record(again.path)}')
        waiting = PartMaker().target('root.children.2')
        self.plan_order.set_part_record(waiting.path, {'state': 'waiting', 'target': 3}, None)
        sent = waiting.send(self.plan_order, None, {})
        print(f'A waiting target sent when its tick comes: {sent[0][1]["outcome"]} for {self.plan_order.requests[-1][3]}, record {self.plan_order.part_record(waiting.path)}')
        trailing = OrderPart('root.children.3', [], None, 'protect', TrailPricing(decimal.Decimal('5'), None, decimal.Decimal('1'), 1), False)
        self.plan_order.set_part_record(trailing.path, {'state': 'pending'}, None)
        trailing.start(self.plan_order, 10, None, {'reliance': {'last_price': 1000.05}})
        print(f"A trailing stop placed: {self.plan_order.requests[-1]}; moved at 1003: {trailing.move(self.plan_order, {'reliance': {'last_price': 1003.00}}, 0.0)}, at 1001: {trailing.move(self.plan_order, {'reliance': {'last_price': 1001.00}}, 0.0)}")
        print(f'Last request: {self.plan_order.requests[-1]}; a stop that does not trail moves: {self.part.move(self.plan_order, {}, 0.0)}')
        print(f'Messages: {self.plan_order.messages}')


if __name__ == '__main__':
    LifecycleUnderAJoinExample().run()
