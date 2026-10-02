"""Shows how an order part takes a change a caller made through `PUT /api/orders/modify`, so the plan carries on from it instead of undoing it.

A caller can change a plan's broker order at the broker, or change a part that has not been sent yet. This program walks through the four things an `OrderPart` does with such a change.

1. A buy of ten sent all at once is cut to six at the broker. `keeps_caller_quantity` answers True, because that one broker order is the whole part, so `take_caller_change(-4)` records the cut. `total` is then six, and a later `set_target(10)` from a join still leaves it at six, so no request goes out to put the four back.
2. The same buy sent as an iceberg answers False, because its later pieces are sized from what is still to trade, so its total stays ten.
3. `with_caller_prices` lays the price and trigger the caller set on a part still waiting over what its pricing made: a stop-limit takes both, a stop-market given a price becomes a stop-limit, a market order given a price becomes a limit, and a stop the pricing sent as a plain limit keeps no trigger. `order` applies the same rule to a stop still waiting.
4. A trailing stop protecting the buy rests at 995.05 behind a best price of 1,000.05. The caller loosens it to 990, and `carry_on` moves the trail's best price to 995, so a tick at 996 moves the stop up to 991 rather than snapping it back to 995.05. A stop that does not trail has nothing to carry on.

A stand-in plays the plan order: it keeps the parts' records and turns every order into an acknowledged leg, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_5_a_callers_change.py
"""

import copy
import decimal

from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.iceberg_execution import (
    IcebergExecution,
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

    A cancel is treated as confirmed at once, a fill is written onto a leg by `fill`, and a caller's change is written onto a leg by `caller_changes`, so a program can walk parts through what a broker would report without any broker.

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
        self.requests.append((
            'place',
            role,
            leg.transaction_type,
            leg.quantity,
            order.get('order_type'),
            str(leg.trigger_price),
            str(leg.price),
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
        self.requests.append((
            'move',
            leg.role,
            str(trigger_price),
            str(price),
        ))
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

    def caller_changes(self, leg, quantity, price, trigger_price):
        """Writes a caller's change onto a leg, as the broker's answer to `PUT /api/orders/modify` would, and keeps what the leg held before.

        Args:
            leg (OrderLeg): The leg the caller changed.
            quantity (int | None): Its new quantity, or None to leave it.
            price (decimal.Decimal | None): Its new limit price, or None to leave it.
            trigger_price (decimal.Decimal | None): Its new trigger price, or None to leave it.

        Returns:
            dict: What the leg held before, with `quantity`, `price` and `trigger_price`.
        """
        before = {
            'quantity': leg.quantity,
            'price': leg.price,
            'trigger_price': leg.trigger_price,
        }
        if quantity is not None:
            leg.quantity = quantity
        if price is not None:
            leg.price = price
        if trigger_price is not None:
            leg.trigger_price = trigger_price
        return before


class ACallersChangeExample:
    """Hands four kinds of caller's change to order parts and prints what each part made of it."""

    def entry(self, execution):
        """The caller's own buy of ten at 1,000, under the root path.

        Args:
            execution (object | None): How its quantity is sent, or None for all at once.

        Returns:
            OrderPart: The part.
        """
        return OrderPart(
            'root',
            [],
            None,
            None,
            FixedPricing(None, None),
            True,
            execution,
        )

    def quantity_cut(self):
        """Cuts a buy sent all at once from ten to six, and shows that a later target keeps the cut.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = self.entry(None)
        pending = {
            'state': 'pending',
        }
        plan_order.set_part_record(part.path, pending, None)
        part.start(plan_order, None, None, {})
        print(f'Sent all at once: {plan_order.requests}, total {part.total(plan_order)}')
        leg = plan_order.parent.legs[0]
        before = plan_order.caller_changes(leg, 6, None, None)
        print(f"The caller cut its broker order from {before['quantity']} to {leg.quantity}; keeps the caller's quantity: {part.keeps_caller_quantity()}")
        count = len(plan_order.messages)
        part.take_caller_change(plan_order, leg.quantity - before['quantity'])
        print(f"Recorded: caller_change {plan_order.part_record(part.path)['caller_change']}, total now {part.total(plan_order)}")
        plan_order.fill(part.path, 2)
        part.set_target(plan_order, 10)
        print(f"2 filled, then a join sets the target to 10: total {part.total(plan_order)}, broker order still {leg.quantity}, requests after the placement {plan_order.requests[1:]}")
        print(f'Messages: {plan_order.messages[count:]}')

    def iceberg_keeps_its_total(self):
        """Shows that a buy sent as an iceberg keeps its total when one piece is changed.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = self.entry(IcebergExecution(3, 0))
        print(f"Sent as an iceberg of 3 at a time: keeps the caller's quantity {part.keeps_caller_quantity()}, total stays {part.total(plan_order)}")

    def caller_prices(self):
        """Lays a caller's price and trigger over the bodies a pricing could make, and over a waiting stop's order.

        Returns:
            None: This method returns nothing.
        """
        part = OrderPart(
            'root.children.0',
            [],
            None,
            'protect',
            NativeStopPricing(decimal.Decimal('990'), decimal.Decimal('988')),
            False,
        )
        record = {
            'state': 'waiting',
            'caller_price': '978.00',
            'caller_trigger_price': '980.00',
        }
        bodies = [
            {
                'order_type': 'SL',
                'trigger_price': '990.00',
                'price': '988.00',
            },
            {
                'order_type': 'SL-M',
                'trigger_price': '990.00',
            },
            {
                'order_type': 'MARKET',
            },
            {
                'order_type': 'LIMIT',
                'price': '985.00',
            },
        ]
        for body in bodies:
            described = dict(body)
            print(f'Priced {described} with the caller at 980 and 978: {part.with_caller_prices(body, record)}')
        plan_order = StandInPlanOrder()
        plan_order.set_part_record(part.path, record, None)
        order = part.order(plan_order, {})
        print(f"The waiting stop's order: {order['transaction_type']} {order['quantity']} {order['order_type']}, trigger {order['trigger_price']}, limit {order['price']}")

    def trail_carries_on(self):
        """Loosens a trailing stop's trigger and shows the trail carrying on from it.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = OrderPart(
            'root.children.0',
            [],
            None,
            'protect',
            TrailPricing(decimal.Decimal('5'), None, decimal.Decimal('1'), 1),
            False,
        )
        pending = {
            'state': 'pending',
        }
        placed_at = {
            'reliance': {
                'last_price': 1000.05,
            },
        }
        risen = {
            'reliance': {
                'last_price': 996.00,
            },
        }
        plan_order.set_part_record(part.path, pending, None)
        part.start(plan_order, 10, None, placed_at)
        print(f"Trailing stop placed: {plan_order.requests[-1]}, memory {plan_order.part_record(part.path)['pricing_memory']}")
        leg = plan_order.parent.legs[0]
        before = plan_order.caller_changes(leg, None, decimal.Decimal('989'), decimal.Decimal('990'))
        part.carry_on(plan_order, leg, before, {}, 0.0)
        print(f"The caller loosened it to {leg.trigger_price}: memory {plan_order.part_record(part.path)['pricing_memory']}")
        print(f'Message: {plan_order.messages[-1]}')
        moved = part.move(plan_order, risen, 0.0)
        print(f'A tick at 996: moved {moved}, {plan_order.requests[-1]}')
        fixed = OrderPart(
            'root.children.1',
            [],
            None,
            'protect',
            FixedPricing(decimal.Decimal('1010'), None),
            False,
        )
        count = len(plan_order.messages)
        fixed.carry_on(plan_order, leg, before, {}, 0.0)
        print(f'A target that does not move records {len(plan_order.messages) - count} messages')

    def differences_in_words(self):
        """Prints how a caller's total change is put into words in the event log.

        Returns:
            None: This method returns nothing.
        """
        for difference in (
            -4,
            2,
        ):
            print(f'A total change of {difference} reads as: {OrderPart.difference_described(difference)}')

    def run(self):
        """Prints each change.

        Returns:
            None: This method returns nothing.
        """
        self.quantity_cut()
        self.iceberg_keeps_its_total()
        self.caller_prices()
        self.trail_carries_on()
        self.differences_in_words()


if __name__ == '__main__':
    ACallersChangeExample().run()
