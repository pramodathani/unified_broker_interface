"""Shows that an order part places its orders under its own path, only ever looks at its own broker orders, and flips its side when it protects a position.

Every broker order an `OrderPart` places carries the part's path as its role, and the part only looks at orders with that role. This is the rule that lets parts share one parent: today's order types each assume they own every leg, so a second type's leg would confuse them. This program builds a parent holding a filled order for the part `root` and a resting order for another part, `root.first`, and shows that `root` is done while `root.first` is not.

It then builds a part that protects the position the caller's buy opened, waiting for the last price to fall to 995 and resting a native stop, and walks it through a small stand-in for the plan order, which records each broker order instead of sending it: what it watches and whether it reads quotes, whether its resting order is looked at on every tick and what its pricing readies when the plan is placed, the context its pricing sees, which is the parent's own instrument and body for an order that names none of its own, the side it sends, readying and asking its trigger, the order it builds, placing it, and the part as a dry run would show it, from `expanded`.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_part/OrderPart/example_2_sees_only_its_own_legs.py
"""

import decimal

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
from unified_broker_interface.utilities.order_engine.utilities.price_crosses_condition import (
    PriceCrossesCondition,
)


class StandInPlanOrder:
    """Stands in for the plan order a part is run through, recording each order instead of sending it.

    Attributes:
        parent (ParentOrder): The parent, whose body is the caller's buy of ten.
        placed (list): Each order placed, as `(role, transaction_type, order_type, trigger_price, price)`.
        group_margin_legs (OrderLegs | None): The group a Together join hands the broker selector, which is none here.
    """

    def __init__(self):
        """Builds the stand-in with a body that names no broker.

        Returns:
            None: This method returns nothing.
        """
        self.parent = ParentOrder('parent-2')
        self.parent.body = {
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 10,
            'price': '1000.00',
        }
        self.placed = []
        self.group_margin_legs = None

    def view(self, quotes, instrument_id=None):
        """The instrument's quote as a market view, with a tick size of 0.05.

        Args:
            quotes (dict): Quotes by instrument id.
            instrument_id (str | None): The instrument, or None for the order's own.

        Returns:
            MarketView: The view.
        """
        return MarketView(quotes.get(instrument_id or 'reliance'), decimal.Decimal('0.05'))

    def part_record(self, path):
        """The part's record, which is empty, since no join has set a target here.

        Args:
            path (str): The part's path.

        Returns:
            dict: An empty record.
        """
        del path
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
        """The broker earlier orders went to, which is none yet.

        Returns:
            None: No broker has been chosen.
        """
        return None

    def place_leg(self, role, order, started_at, broker_name):
        """Records the order and answers that it was accepted.

        Args:
            role (str): The leg's role, which a part sets to its path.
            order (dict): The order.
            started_at (float | None): Unused.
            broker_name (str | None): Unused.

        Returns:
            tuple: The answer (dict), its HTTP status (int) and the leg (None here).
        """
        del started_at, broker_name
        self.placed.append((
            role,
            order['transaction_type'],
            order['order_type'],
            order.get('trigger_price'),
            order['price'],
        ))
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
            None,
            None,
            NativeStopPricing(decimal.Decimal('990'), decimal.Decimal('988')),
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
                'hidden_stop',
            ],
            PriceCrossesCondition(decimal.Decimal('995'), None, 'last', None, 'none', None),
            'protect',
            NativeStopPricing(decimal.Decimal('990'), decimal.Decimal('988')),
        )
        print(f'Protecting part: watches {part.instruments()}, reads quotes {part.needs_prices()}, closes a position {part.closes_position()}')
        print(f'Looked at on every tick once resting: {part.moves_on_ticks()}, pricing memory readied when placed: {part.prepared_pricing_memory(plan_order)}')
        print(f'It trades the parent\'s own instrument with the caller\'s body: {part.context(plan_order).is_parents_instrument()}, quantity {part.context(plan_order).body["quantity"]}')
        print(f"Sends {part.sending_side('BUY')} for a position opened with a BUY")
        memory = {}
        part.prepare(plan_order, memory)
        steady = {
            'reliance': {
                'last_price': 1000.05,
            },
        }
        fallen = {
            'reliance': {
                'last_price': 994.90,
            },
        }
        print(f'Triggered at 1000.05: {part.is_triggered(plan_order, memory, steady, 0.0)}')
        print(f'Triggered at 994.90: {part.is_triggered(plan_order, memory, fallen, 1.0)}')
        print(f'Order it builds: {part.order(plan_order, fallen)}')
        body, status = part.place(plan_order, None, fallen)
        print(f"Placed: HTTP {status}, {body['outcome']}, as {plan_order.placed}")
        print(f'As a dry run shows it: {part.expanded()}')

if __name__ == '__main__':
    SeesOnlyItsOwnLegsExample().run()
