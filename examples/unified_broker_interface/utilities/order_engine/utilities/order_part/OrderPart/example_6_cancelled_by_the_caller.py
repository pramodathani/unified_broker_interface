"""Cancels three orders for a caller: one already resting at its broker, one whose turn has not come, and one waiting for its trigger.

`OrderPart.cancel_for_caller` is what `PlanOrder.cancel_part` asks of the part a caller names. A working order is marked `ended`, so it sends nothing more, and its resting broker order is cancelled; it is marked done only by the settle that follows the broker's confirmation. An order whose turn has not come is marked `ended` but left pending, so the join above it still starts its siblings when the turn comes, and `start` then marks it done as `cancelled` without sending anything. An order waiting for its trigger is marked done as `cancelled` at once.

A stand-in plays the plan order: it keeps the parts' records, turns every order into an acknowledged leg, and accepts a cancel without confirming it until asked, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_6_cancelled_by_the_caller.py
"""

import copy
import datetime
import decimal

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
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
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    PriceCrossesCondition,
)

PLACED_AT = datetime.datetime(2026, 9, 23, 10, 0, 0, tzinfo=moments.INDIA)

REASON = "the caller cancelled the plan's root part"


class StandInPlanOrder:
    """Stands in for the plan order: keeps the parts' records in the parent's parameters, and turns every order placed into a leg the broker has acknowledged, noting each request.

    A cancel is accepted but only confirmed by `confirm_cancels`, and a fill is written onto a leg by `fill`, so a program can walk parts through what a broker would report without any broker.

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
        """Asks for a leg to be cancelled, which the broker accepts but has not yet confirmed, so the leg keeps resting until `confirm_cancels`.

        Args:
            leg (OrderLeg): The leg.
            reason (str): Unused.

        Returns:
            bool: True, since the cancel is accepted.
        """
        del reason
        self.requests.append(('cancel', leg.role))
        return True

    def confirm_cancels(self):
        """Marks every leg whose cancel was asked for as cancelled, as the broker's order update would.

        Returns:
            None: This method returns nothing.
        """
        cancelled_roles = []
        for request in self.requests:
            if request[0] == 'cancel':
                cancelled_roles.append(request[1])
        for leg in self.parent.legs:
            if leg.role in cancelled_roles and not leg.is_finished():
                leg.state = 'cancelled'

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

    def trading_segment(self):
        """The segment whose calendar the order's times follow.

        Returns:
            str: `nse_equity`.
        """
        return 'nse_equity'

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


class CancelledByTheCallerExample:
    """Cancels orders for a caller at three points in their lives and prints what each one did."""

    def part_with(self, trigger=None):
        """An order part sent at the body's own price.

        Args:
            trigger (object | None): The trigger, or None to be sent at once.

        Returns:
            OrderPart: The part.
        """
        return OrderPart(
            'root',
            [],
            trigger,
            None,
            FixedPricing(None, None),
            True,
        )

    def working(self):
        """Cancels an order resting at its broker, and settles it before and after the broker confirms the cancel.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = self.part_with()
        plan_order.set_part_record('root', {'state': 'pending'}, None)
        part.start(plan_order, None, None, {}, PLACED_AT.timestamp())
        print(f"Working: record {plan_order.part_record('root')}")
        all_cancelled = part.cancel_for_caller(plan_order, REASON)
        print(f"Cancelled for the caller: {all_cancelled}, record {plan_order.part_record('root')}")
        part.settle(plan_order)
        print(f"Settled before the broker confirms: state {plan_order.part_record('root')['state']}, leg {plan_order.parent.legs[0].state}")
        plan_order.confirm_cancels()
        part.settle(plan_order)
        print(f"Settled after the broker confirms: record {plan_order.part_record('root')}")
        print(f'Requests: {plan_order.requests}')
        print(f'Messages: {plan_order.messages}')

    def turn_not_come(self):
        """Cancels an order whose turn has not come, then starts it as its join would.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = self.part_with()
        plan_order.set_part_record('root', {'state': 'pending'}, None)
        all_cancelled = part.cancel_for_caller(plan_order, REASON)
        print(f"Turn not come, cancelled for the caller: {all_cancelled}, record {plan_order.part_record('root')}")
        placed = part.start(plan_order, None, None, {}, PLACED_AT.timestamp())
        print(f"Started when its turn comes: placed {placed}, record {plan_order.part_record('root')}")
        print(f'Requests: {plan_order.requests}')
        print(f'Messages: {plan_order.messages}')

    def waiting(self):
        """Cancels an order still waiting for its trigger.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        trigger = PriceCrossesCondition(decimal.Decimal('950'), None, 'last', None, 'none', None)
        part = self.part_with(trigger)
        plan_order.set_part_record('root', {'state': 'pending'}, None)
        part.start(plan_order, None, None, {}, PLACED_AT.timestamp())
        print(f"Waiting: record {plan_order.part_record('root')}")
        all_cancelled = part.cancel_for_caller(plan_order, REASON)
        print(f"Cancelled for the caller: {all_cancelled}, record {plan_order.part_record('root')}, requests {plan_order.requests}")

    def run(self):
        """Prints each order's cancel.

        Returns:
            None: This method returns nothing.
        """
        self.working()
        self.turn_not_come()
        self.waiting()


if __name__ == '__main__':
    CancelledByTheCallerExample().run()
