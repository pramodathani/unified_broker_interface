"""Holds a two-rung ladder in the engine: each rung is placed only when the offer reaches it, and held again after its profit is taken.

With `holds_rungs` set, as the plan reader sets it when the order is held, `ScaleWithProfitTakerPart.start` lays the rungs out as pending and places none; `moves_on_ticks` asks the plan to call `move` on every tick, and `move` places each rung `reached` says the offer has come to, through `place_rung`, which records the virtual book's estimate of what a resting rung would have filled as its `missed_quantity`. The profit-taker rests at the broker as soon as its rung fills, and when it fills the rung is pending again; `finish_when_done` keeps the part working while a rung is pending. A stand-in plays the plan order and Redis, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/scale_with_profit_taker_part/ScaleWithProfitTakerPart/example_3_holding_its_rungs.py
"""

import copy
import decimal
import json
import logging

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.scale_with_profit_taker_part import (
    ScaleWithProfitTakerPart,
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
        transaction_type (str): BUY or SELL.
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


class StandInCache:
    """Stands in for Redis, holding the virtual book's one estimate: what a resting order at the first rung would have filled.

    Attributes:
        estimates (dict): The estimates, by key.
    """

    def __init__(self):
        """Builds the cache with the first rung's estimate.

        Returns:
            None: This method returns nothing.
        """
        self.estimates = {
            'parent-1/root/rung0.0': json.dumps({
                'queue_filled': 3,
            }),
        }

    def hget(self, key, field):
        """One estimate.

        Args:
            key (str): Unused, the estimates' hash.
            field (str): The estimate's key.

        Returns:
            str | None: The estimate, or None.
        """
        del key
        return self.estimates.get(field)


class StandInPlacement:
    """Stands in for the placement, which reads the catalogue, the live quote and Redis.

    Attributes:
        quote (dict | None): RELIANCE's live quote.
        cache (StandInCache): Redis.
    """

    def __init__(self, quote):
        """Builds the placement.

        Args:
            quote (dict | None): The live quote.

        Returns:
            None: This method returns nothing.
        """
        self.quote = quote
        self.cache = StandInCache()

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
        parent (ParentOrder): The parent, holding the caller's buy of twenty RELIANCE and the legs placed.
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
            'quantity': 20,
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
        self.logger = logging.getLogger('example')

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
        order.transaction_type = body['transaction_type']
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
        self.requests.append(('place', leg.transaction_type, leg.quantity, order['price']))
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


class HoldingItsRungsExample:
    """Walks a held ladder through a release, a profit and a second hold."""

    def quotes(self, mid):
        """RELIANCE's quote at a middle price, keyed as the plan reads it.

        Args:
            mid (float): The middle price.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            'RELIANCE': book(mid),
        }

    def run(self):
        """Prints what each step sends and what the part remembers.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder(1001.0)
        part = ScaleWithProfitTakerPart('root', 'scale_with_profit_taker', {
                'from_price': 1000,
                'to_price': 995,
                'steps': 2,
                'profit_points': 4,
            })
        part.holds_rungs = True
        plan_order.parent.parameters['parts']['root'] = {
            'state': 'working',
        }
        print(f'moves on ticks: {part.moves_on_ticks()}')
        part.start(plan_order, None, None, {})
        print('placed at start:', plan_order.requests)
        print('rungs pending:', [rung['pending'] for rung in part.own_memory(plan_order)['rungs']])
        view = plan_order.view(self.quotes(1000.95))
        print(f'offer 1001.00 reaches 1000: {part.reached(view, "BUY", decimal.Decimal("1000"))}')
        print('move at offer 1001.00 places:', part.move(plan_order, self.quotes(1000.95), 0))
        print('move at offer 1000.00 places:', part.move(plan_order, self.quotes(999.95), 0), plan_order.requests)
        print('first rung remembers:', part.own_memory(plan_order)['rungs'][0])
        plan_order.fill(1)
        part.settle(plan_order)
        print('after the rung fills, sent:', plan_order.requests[-1])
        plan_order.fill(2)
        part.settle(plan_order)
        print('after the profit is taken, rung pending again:', part.own_memory(plan_order)['rungs'][0]['pending'])
        part.finish_when_done(plan_order)
        print('part state while a rung is pending:', plan_order.part_record('root')['state'])
        before = len(plan_order.requests)
        part.place_rung(plan_order, 'BUY', 1, None)
        print('placing the 995 rung by hand sends:', plan_order.requests[before:])


if __name__ == '__main__':
    HoldingItsRungsExample().run()
