"""Shows the stop filling: part of it shrinks the furthest target, all of it cancels the rest once, and the exits are then done.

`fit_targets` cuts the resting targets from the furthest first to what the stop has left, and `cancel_once` asks for each cancel only once, though the plan settles again on every confirmation. With fewer units than targets, the last target takes it all. `settings_problems` lists every bad setting in today's words. A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/scale_out_exits_part/ScaleOutExitsPart/example_2_the_stop_fills_and_refusals.py
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
from unified_broker_interface.utilities.order_engine.utilities.scale_out_exits_part import (
    ScaleOutExitsPart,
)


def book(mid):
    """A quote whose best bid and offer sit a tick either side of a middle price.

    Args:
        mid (float | None): The middle, or None for a quote with an empty book.

    Returns:
        dict: The quote.
    """
    if mid is None:
        return {
            'depth': {
                'buy': [],
                'sell': [],
            },
        }
    return {
        'last_price': mid,
        'depth': {
            'buy': [
                {
                    'price': round(mid - 0.05, 2),
                    'quantity': 100,
                },
            ],
            'sell': [
                {
                    'price': round(mid + 0.05, 2),
                    'quantity': 100,
                },
            ],
        },
    }


class StandInOrder(dict):
    """Stands in for a validated order: the body itself, with its quantity as a number, which also answers the tick size the brokers agree on.

    Attributes:
        quantity (int): The quantity.
    """

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
        quote = book(last_price)
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
        order = StandInOrder(body)
        order.quantity = int(body['quantity'])
        return order

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
        self.requests.append(('place', leg.transaction_type, leg.quantity, order['order_type'], order['price']))
        return {
            'outcome': 'accepted',
            'order_id': leg.broker_order_id,
            'broker': 'zerodha',
        }, 200, leg.leg_id

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

    def tick_size(self):
        """RELIANCE's tick size.

        Returns:
            decimal.Decimal: 0.05.
        """
        return decimal.Decimal('0.05')

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

    def reprice_leg(self, leg, price, trigger_price, reason):
        """Moves a leg's limit price, as the broker would once it accepts the change.

        Args:
            leg (OrderLeg): The leg.
            price (decimal.Decimal): Its new limit price.
            trigger_price (decimal.Decimal | None): Unused.
            reason (str): Why.

        Returns:
            bool: True, since the change is accepted.
        """
        del trigger_price
        self.requests.append(('move', leg.transaction_type, str(price), reason))
        leg.price = float(price)
        return True

    def reduce_leg(self, leg, quantity, reason):
        """Changes a leg's quantity, as the broker would once it accepts the change.

        Args:
            leg (OrderLeg): The leg.
            quantity (int): Its new total quantity.
            reason (str): Why.

        Returns:
            bool: True, since the change is accepted.
        """
        self.requests.append(('change', leg.transaction_type, quantity, reason))
        leg.quantity = quantity
        return True

    def enter(self, filled, average_price):
        """Adds the entry the exits protect, as the first plan of a Then join would have placed it, filled.

        Args:
            filled (int): How much it filled.
            average_price (float): The average price it filled at.

        Returns:
            None: This method returns nothing.
        """
        leg = OrderLeg('parent-1:0', 'root.first')
        leg.state = 'filled'
        leg.transaction_type = 'BUY'
        leg.quantity = filled
        leg.filled_quantity = filled
        leg.average_price = average_price
        self.parent.legs.append(leg)

    def fill(self, number, quantity=None):
        """Fills one leg, wholly or in part, as an order update would.

        Args:
            number (int): The leg's place among the legs, from one.
            quantity (int | None): How much has filled in all, or None for all of it.

        Returns:
            None: This method returns nothing.
        """
        leg = self.parent.legs[number - 1]
        if quantity is None:
            quantity = leg.quantity
        leg.filled_quantity = quantity
        if quantity >= leg.quantity:
            leg.state = 'filled'


class ExitsMaker:
    """Builds the exits as the reader would under a Then join."""

    def exits(self, settings):
        """The exits, sized by the entry's fills and protecting what `root.first` opened.

        Args:
            settings (dict): The exits' settings.

        Returns:
            ScaleOutExitsPart: The part.
        """
        part = ScaleOutExitsPart('root.each_fill', 'scale_out_exits', settings, False, {})
        part.sized_by_fills = True
        part.opened_by = [
            'root.first',
        ]
        return part


class TheStopFillsAndRefusalsExample:
    """Fills the stop in two steps, arms a tiny position, and checks the refusals."""

    def run(self):
        """Prints what each step did.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder(1000.0)
        plan_order.enter(10, 1000.0)
        part = ExitsMaker().exits({
                'stop_price': 990,
                'stop_limit_price': 988,
                'target_prices': [
                    1010,
                    1020,
                ],
            })
        part.start(plan_order, 10, None, {})
        plan_order.fill(2, 6)
        part.settle(plan_order)
        print('the stop fills 6:', plan_order.requests[3:])
        plan_order.fill(2)
        part.settle(plan_order)
        part.settle(plan_order)
        print('the stop fills 10:', plan_order.requests[5:])
        for leg in part.target_legs(plan_order):
            leg.state = 'cancelled'
        part.settle(plan_order)
        print('state:', plan_order.part_record('root.each_fill')['state'], plan_order.part_record('root.each_fill')['reason'])
        tiny = StandInPlanOrder(1000.0)
        tiny.enter(1, 1000.0)
        ExitsMaker().exits({
                'stop_price': 990,
                'stop_limit_price': 988,
                'target_prices': [
                    1010,
                    1020,
                ],
            }).start(tiny, 1, None, {})
        print('one unit:', tiny.requests)
        bad = ExitsMaker().exits(
            {
                'stop_price': 990,
                'target_prices': [
                    1010,
                ],
                'breakeven_after': 0,
                'trail': 5,
            },
        )
        for problem in bad.settings_problems():
            print('problem:', problem)


if __name__ == '__main__':
    TheStopFillsAndRefusalsExample().run()
