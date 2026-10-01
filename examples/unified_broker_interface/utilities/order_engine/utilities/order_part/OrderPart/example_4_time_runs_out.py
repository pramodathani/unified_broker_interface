"""Walks three orders whose lifetime runs out: one closes what it filled, one is made marketable, and one still waiting is simply done.

`OrderPart.lifetime_ends_at` works out when an order's lifetime ends, here from a fixed moment so the output does not change. `end_lifetime` does nothing before then. When the time comes, an order that closes what it filled cancels what still rests first and then sends a market order the other way for what traded, under the path `root.close`; an order made marketable has its resting order moved two ticks past the other side's touch; and an order still waiting for its trigger is done as expired.

A stand-in plays the plan order: it keeps the parts' records and turns every order into an acknowledged leg, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_4_time_runs_out.py
"""

import copy
import datetime
import decimal

from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.lifetime import (
    Lifetime,
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


class TimeRunsOutExample:
    """Walks orders through the end of their lifetimes."""

    def part_with(self, lifetime, trigger=None):
        """An order part sent at the body's own price, with a lifetime.

        Args:
            lifetime (Lifetime): The lifetime.
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
            None,
            None,
            None,
            None,
            lifetime,
        )

    def close_filled(self):
        """Ends a working order that has filled four by closing them.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = self.part_with(Lifetime('10:30', None, 'both', 'close_filled'))
        ends_at = part.lifetime_ends_at(plan_order, PLACED_AT)
        print(f'Ends at {datetime.datetime.fromtimestamp(ends_at, moments.INDIA).strftime("%H:%M")}')
        plan_order.set_part_record('root', {'state': 'pending', 'ends_at': ends_at}, None)
        part.start(plan_order, None, None, {}, PLACED_AT.timestamp())
        plan_order.fill('root', 4)
        print(f'Before its time: {part.end_lifetime(plan_order, {}, ends_at - 1)}')
        print(f'At its time: {part.end_lifetime(plan_order, {}, ends_at)}, and again: {part.end_lifetime(plan_order, {}, ends_at)}')
        print(f'Requests: {plan_order.requests}')
        print(f'Record: {plan_order.part_record("root")}')

    def made_marketable(self):
        """Ends a working order by moving it past the other side's touch.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        part = self.part_with(Lifetime(None, 20, 'working', 'marketable'))
        ends_at = part.lifetime_ends_at(plan_order, PLACED_AT)
        plan_order.set_part_record('root', {'state': 'pending', 'ends_at': ends_at}, None)
        part.start(plan_order, None, None, {}, PLACED_AT.timestamp())
        quotes = {
            'reliance': {
                'depth': {
                    'buy': [
                        {
                            'price': 1001.00,
                            'quantity': 100,
                        },
                    ],
                    'sell': [
                        {
                            'price': 1001.05,
                            'quantity': 100,
                        },
                    ],
                },
            },
        }
        print(f'Twenty minutes on: {part.end_lifetime(plan_order, quotes, ends_at)}, requests {plan_order.requests}')

    def waiting_expires(self):
        """Ends an order still waiting for its trigger.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        trigger = PriceCrossesCondition(decimal.Decimal('950'), None, 'last', None, 'none', None)
        part = self.part_with(Lifetime('10:30', None, 'waiting', 'cancel'), trigger)
        ends_at = part.lifetime_ends_at(plan_order, PLACED_AT)
        plan_order.set_part_record('root', {'state': 'pending', 'ends_at': ends_at}, None)
        part.start(plan_order, None, None, {}, PLACED_AT.timestamp())
        print(f'Waiting at its time: {part.end_lifetime(plan_order, {}, ends_at)}, record {plan_order.part_record("root")}')
        print(f'As a dry run shows its lifetime: {part.expanded()["order"]["slots"]["lifetime"]}')

    def run(self):
        """Prints each order's end.

        Returns:
            None: This method returns nothing.
        """
        self.close_filled()
        self.made_marketable()
        self.waiting_expires()


if __name__ == '__main__':
    TimeRunsOutExample().run()
