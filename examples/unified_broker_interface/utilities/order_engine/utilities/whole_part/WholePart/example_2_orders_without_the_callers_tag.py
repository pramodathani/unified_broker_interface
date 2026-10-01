"""Shows a part kept whole inside a join, whose orders do not carry the caller's tag, with a quantity of its own.

Only the plan's main order keeps the caller's tag, as today's exits do, so a part made with `keeps_tag` false leaves the tag off every limit it builds, unless the order names a tag of its own. An order's own `quantity` is written over the body's. A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/whole_part/WholePart/example_2_orders_without_the_callers_tag.py
"""

import copy
import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
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
    """Stands in for the plan order: keeps the parts' records, turns every order placed into a leg the broker has acknowledged, and notes each request.

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
            tuple: The answer (dict), its HTTP status (int) and the leg (OrderLeg).
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
        self.requests.append(('place', leg.transaction_type, leg.quantity, order['price'], order.get('tag')))
        return {
            'outcome': 'accepted',
            'order_id': leg.broker_order_id,
            'broker': 'zerodha',
        }, 200, leg

    def cancel_leg(self, leg, reason):
        """Cancels a leg, as the broker would once it confirms the cancel.

        Args:
            leg (OrderLeg): The leg.
            reason (str): Why.

        Returns:
            bool: True, since the cancel is accepted.
        """
        self.requests.append(('cancel', leg.transaction_type, leg.price, reason))
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
        return MarketView(quotes.get('RELIANCE'), decimal.Decimal('0.05'))

    def fill(self, number):
        """Fills one leg completely, as an order update would.

        Args:
            number (int): The leg's place in the order placed, from one.

        Returns:
            None: This method returns nothing.
        """
        leg = self.parent.legs[number - 1]
        leg.filled_quantity = leg.quantity
        leg.state = 'filled'


class OrdersWithoutTheCallersTagExample:
    """Builds orders for three parts that differ in tag and quantity."""

    def run(self):
        """Prints each part's order.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder(1000.0)
        parts = [
            (
                'the main order',
                WholePart('root', 'grid', {}, True, {}),
            ),
            (
                'inside a join',
                WholePart('root.then.0', 'grid', {}, False, {
                    'quantity': 2,
                }),
            ),
            (
                'with its own tag',
                WholePart('root.then.1', 'grid', {}, False, {
                    'tag': 'hedge',
                }),
            ),
        ]
        for label, part in parts:
            order = part.limit_order(plan_order, 'SELL', decimal.Decimal('1005.00'))
            print(f'{label}: {order["transaction_type"]} {order["quantity"]} at {order["price"]}, tag {order.get("tag")}')


if __name__ == '__main__':
    OrdersWithoutTheCallersTagExample().run()
