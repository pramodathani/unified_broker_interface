"""Watches a RELIANCE position against a band of minus ten to ten, hedges when a hundred is held, and does not hedge twice.

`ExposureHedgePart.start` places nothing. On each tick `move` reads the account's positions, `exposure` adds them up at their exposure per unit together with `hedges_in_flight`, the hedges already sent, and when the total is outside the band a sell goes out two ticks under the bid, sized to bring the total back to the middle. The next tick sees the hedge in flight and sends nothing more, even before the position catches up. `held` reads one instrument out of the positions document and `hedge_price` is the hedge's price. A stand-in plays the plan order, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/exposure_hedge_part/ExposureHedgePart/example_1_out_of_band_and_back.py
"""

import copy
import decimal

from unified_broker_interface.utilities.order_engine.utilities.exposure_hedge_part import (
    ExposureHedgePart,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
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
    """Stands in for the placement, which reads the catalogue, the live quote and the account's positions.

    Attributes:
        quote (dict | None): RELIANCE's live quote.
        positions (dict): The positions document, whose `net` list holds the account's RELIANCE position.
    """

    def __init__(self, quote):
        """Builds the placement with no position held.

        Args:
            quote (dict | None): The live quote.

        Returns:
            None: This method returns nothing.
        """
        self.quote = quote
        self.positions = {
            'net': [],
        }

    def hold(self, quantity):
        """Sets the account's RELIANCE position, as the position poller would.

        Args:
            quantity (int): The signed quantity.

        Returns:
            None: This method returns nothing.
        """
        self.positions = {
            'net': [
                {
                    'instrument_id': 'RELIANCE',
                    'quantity': quantity,
                },
            ],
        }

    def market_context(self, instrument_id, with_quote, with_positions):
        """The instrument, its quote and the account's positions.

        Args:
            instrument_id (str): Unused.
            with_quote (bool): Unused.
            with_positions (bool): Unused.

        Returns:
            tuple: The instrument, the quote and the positions document.
        """
        del instrument_id, with_quote, with_positions
        return StandInInstrument(), self.quote, self.positions


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


class OutOfBandAndBackExample:
    """Holds a position, hedges it and ticks again."""

    def run(self):
        """Prints what each tick did.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder(1000.0)
        part = ExposureHedgePart('root', 'exposure_hedge', {
                'watched': [
                    {
                        'instrument_id': 'RELIANCE',
                        'exposure_per_unit': 1,
                    },
                ],
                'hedge_instrument_id': 'RELIANCE',
                'lower_band': -10,
                'upper_band': 10,
            })
        print(f'problems {part.settings_problems()}, trades {part.context(plan_order).instrument_id}, needs prices {part.needs_prices()}, moves on ticks {part.moves_on_ticks()}')
        print('start places:', part.start(plan_order, None, None, {}))
        quotes = {
            'RELIANCE': book(1000.0),
        }
        print('flat, hedged:', part.move(plan_order, quotes, 1.0))
        plan_order.placement.hold(100)
        positions = plan_order.placement.positions
        print(f'holding {part.held(positions, "RELIANCE")}, exposure {part.exposure(positions, plan_order.parent)}')
        print('a hundred held, hedged:', part.move(plan_order, quotes, 2.0), plan_order.requests)
        print(f'in flight {part.hedges_in_flight(plan_order.parent)}, exposure {part.exposure(positions, plan_order.parent)}')
        print('next tick, hedged again:', part.move(plan_order, quotes, 3.0))
        view = MarketView(book(1000.0), decimal.Decimal('0.05'))
        print(f'a buy would go at {part.hedge_price(view, "BUY")}, a sell at {part.hedge_price(view, "SELL")}')


if __name__ == '__main__':
    OutOfBandAndBackExample().run()
