"""Shows that a caller's change to the quantity of one of a grid's broker orders does not change how much the grid trades, because a part kept whole sizes its orders by its own rules.

A grid places a buy of five at 995 and a sell of five at 1,005. The caller cuts the buy to three through `PUT /api/orders/modify`. When the plan order hears of a changed quantity it asks the part that placed the order whether it keeps the caller's quantity, and only counts the change with `take_caller_change` when the answer is True. `WholePart.keeps_caller_quantity` answers False, and so does `GridPart`, which inherits it, so the grid's record gains no `caller_change` and the next rung it builds is still five, the size its settings give every rung. An ordinary order sent all at once answers True for the same change, because that one broker order is the whole order.

A stand-in plays the plan order and copies the plan order's rule for a changed quantity, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/whole_part/WholePart/example_3_a_callers_change.py
"""

import copy
import decimal

from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.grid_part import (
    GridPart,
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
from unified_broker_interface.utilities.order_engine.utilities.whole_part import (
    WholePart,
)


class StandInOrder(dict):
    """Stands in for a validated order: the body itself, which also answers the tick size the brokers agree on."""

    def agreed_tick_size(self, handles):
        """The tick size every broker agrees on, which is RELIANCE's.

        Args:
            handles (dict): Unused.

        Returns:
            decimal.Decimal: 0.05.
        """
        del handles
        return decimal.Decimal('0.05')


class StandInInstrument:
    """Stands in for RELIANCE in the catalogue.

    Attributes:
        handles (dict): Each broker's handle.
    """

    def __init__(self):
        """Builds the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'zerodha': {
                'lot_size': 1,
            },
        }


class StandInPlacement:
    """Stands in for the placement, which reads the catalogue and the live quote.

    Attributes:
        quote (dict | None): RELIANCE's live quote.
    """

    def __init__(self, quote):
        """Builds the placement.

        Args:
            quote (dict | None): The live quote.

        Returns:
            None: This method returns nothing.
        """
        self.quote = quote

    def market_context(self, instrument_id, with_quote, with_positions):
        """The instrument and its quote.

        Args:
            instrument_id (str): Unused.
            with_quote (bool): Unused.
            with_positions (bool): Unused.

        Returns:
            tuple: The instrument, the quote and an unused value.
        """
        del instrument_id, with_quote, with_positions
        return StandInInstrument(), self.quote, None


class StandInPlanOrder:
    """Stands in for the plan order: keeps the parts' records, turns every order placed into a leg the broker has acknowledged, notes each request, and counts a caller's changed quantity by the plan order's rule.

    Attributes:
        parent (ParentOrder): The parent, holding the caller's buy of five RELIANCE and the legs placed.
        placement (StandInPlacement): The catalogue and the live quote.
        requests (list): Every request, as a tuple naming what was asked.
        messages (list): Every change of a part's record that would be recorded as an event.
    """

    def __init__(self, last_price):
        """Builds the stand-in with nothing placed.

        Args:
            last_price (float | None): RELIANCE's last traded price, or None when the quote carries none.

        Returns:
            None: This method returns nothing.
        """
        self.parent = ParentOrder('parent-1')
        self.parent.instrument_id = 'RELIANCE'
        self.parent.body = {
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'quantity': 5,
            'price': '1000.00',
            'tag': 'mine',
        }
        self.parent.parameters = {
            'parts': {},
        }
        quote = {
            'last_price': last_price,
        }
        self.placement = StandInPlacement(quote)
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

    def read_order(self, body):
        """Answers with the body itself, standing in for a validated order.

        Args:
            body (dict): The body.

        Returns:
            StandInOrder: The same body.
        """
        return StandInOrder(body)

    def concrete_order(self, order):
        """Answers with the order itself, since it names no references.

        Args:
            order (StandInOrder): The order.

        Returns:
            StandInOrder: The same order.
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
            order (StandInOrder): The order.
            started_at (float | None): Unused.
            broker_name (str | None): Unused.

        Returns:
            tuple: The answer (dict), its HTTP status (int) and the leg's id (str).
        """
        del started_at, broker_name
        number = len(self.parent.legs) + 1
        leg = OrderLeg(f'parent-1:{number}', role)
        leg.state = 'acknowledged'
        leg.broker_order_id = str(number)
        leg.transaction_type = order['transaction_type']
        leg.quantity = order['quantity']
        leg.price = float(order['price'])
        self.parent.legs.append(leg)
        self.requests.append((
            'place',
            leg.transaction_type,
            leg.quantity,
            order['price'],
        ))
        return {
            'outcome': 'accepted',
            'order_id': leg.broker_order_id,
            'broker': 'zerodha',
        }, 200, leg.leg_id

    def view(self, quotes, instrument_id=None):
        """A quote as a market view, with RELIANCE's tick size of 0.05.

        Args:
            quotes (dict): Quotes by instrument id.
            instrument_id (str | None): Unused, since there is one instrument.

        Returns:
            MarketView: The view.
        """
        del instrument_id
        return MarketView(quotes.get('RELIANCE'), decimal.Decimal('0.05'))

    def caller_cuts(self, leg, quantity, part):
        """Writes a caller's new quantity onto a leg, then counts it against the part only when the part keeps the caller's quantity, as the plan order does.

        Args:
            leg (OrderLeg): The leg the caller changed.
            quantity (int): Its new quantity.
            part (OrderPart): The part that placed it.

        Returns:
            bool: True when the change was counted against the part.
        """
        change = quantity - leg.quantity
        leg.quantity = quantity
        if not part.keeps_caller_quantity():
            return False
        part.take_caller_change(self, change)
        return True


class ACallersChangeExample:
    """Cuts one of a grid's rungs and prints that the grid keeps its own sizes."""

    def run(self):
        """Places two rungs, cuts the buy, and compares the grid with an order sent all at once.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder(1000.0)
        settings = {
            'levels': 1,
            'step_points': 5,
            'most_inventory': 10,
        }
        grid = WholePart('root', 'grid', settings)
        buy = grid.limit_order(plan_order, 'BUY', decimal.Decimal('995.00'))
        sell = grid.limit_order(plan_order, 'SELL', decimal.Decimal('1005.00'))
        orders = [
            buy,
            sell,
        ]
        for order in orders:
            grid.place_order(plan_order, order, None)
        print(f'The grid placed: {plan_order.requests}')
        leg = plan_order.parent.legs[0]
        counted = plan_order.caller_cuts(leg, 3, grid)
        print(f"The caller cut the buy at 995 to {leg.quantity}; the grid keeps the caller's quantity: {grid.keeps_caller_quantity()}, so the change was counted: {counted}")
        print(f'The grid\'s record: {plan_order.part_record(grid.path)}, messages {plan_order.messages}')
        next_rung = grid.limit_order(plan_order, 'BUY', decimal.Decimal('990.00'))
        print(f"The next rung it builds is still {next_rung['quantity']}")
        print(f"A GridPart, which inherits the answer, keeps the caller's quantity: {GridPart('root', 'grid', settings).keeps_caller_quantity()}")
        entry = OrderPart(
            'root.first',
            [],
            None,
            None,
            FixedPricing(None, None),
            True,
        )
        entry_plan_order = StandInPlanOrder(1000.0)
        entry_leg = OrderLeg('parent-1:1', entry.path)
        entry_leg.quantity = 5
        counted = entry_plan_order.caller_cuts(entry_leg, 3, entry)
        print(f"An order sent all at once, cut from 5 to 3: keeps the caller's quantity {entry.keeps_caller_quantity()}, counted {counted}, record {entry_plan_order.part_record(entry.path)}")


if __name__ == '__main__':
    ACallersChangeExample().run()
