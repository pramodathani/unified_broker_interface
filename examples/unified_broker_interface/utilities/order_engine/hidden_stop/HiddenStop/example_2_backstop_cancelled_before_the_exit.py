"""Calls a hidden stop's steps by hand on a short with a backstop: arm it, build the exit, and fire it, cancelling the backstop first.

Nothing a `HiddenStop` keeps in the engine protects a position while the engine is down. `backstop_price` and `backstop_limit_price` leave a real stop-loss limit at the broker for that, further away than the hidden level. This program protects a short of 40 INFY with a hidden level of 1,520 and a backstop triggering at 1,540, and calls the steps directly:

- `backstop_prices` reads the backstop's trigger and limit;
- `arm` places the backstop as a buy stop, and the parent becomes `protecting`;
- `child_order` builds the exit from the book when the level is reached, a buy two ticks above the best offer;
- `fire` cancels the backstop first, so it cannot trigger later and open a new position, and only then sends the exit.

A second stop is then armed the same way, and its backstop fills at the broker before the hidden level is ever reached, as it would while the engine was down. `on_leg_update`, which the engine calls with every change to a leg, sees the backstop filled and ends the parent as `completed`, because the position it protected is closed and there is nothing left to watch.

Last, a backstop with only its trigger is refused with HTTP 400, because a stop-limit whose limit sits at its trigger will not fill when the price runs through it. The placement is a stand-in that chooses Zerodha and accepts every order and cancel; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/hidden_stop/HiddenStop/example_2_backstop_cancelled_before_the_exit.py
"""

import decimal
import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.hidden_stop import (
    HiddenStop,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000002'


class StandInAnswer:
    """What the stand-in broker answers a change or a cancel with.

    Attributes:
        outcome (str): `accepted` or `rejected`.
        status_message (str | None): Why, when it was not accepted.
        response_body (dict): The broker's body.
    """

    def __init__(self, outcome, status_message=None):
        """Builds the answer.

        Args:
            outcome (str): `accepted` or `rejected`.
            status_message (str | None): Why, when it was not accepted.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = outcome
        self.status_message = status_message
        self.response_body = {
            'status': 'success' if outcome == 'accepted' else 'error',
        }


class StandInBrokerRequest:
    """A request built for a broker, reduced to what the engine reads from it.

    Attributes:
        tag (str | None): The tag the request carries.
        body (dict): The request's body.
    """

    def __init__(self, tag, body):
        """Builds the request.

        Args:
            tag (str | None): The tag the request carries.
            body (dict): The request's body.

        Returns:
            None: This method returns nothing.
        """
        self.tag = tag
        self.body = body

    def shown(self):
        """The request as the event log and a dry run show it.

        Returns:
            dict: The method, URL and body.
        """
        return {
            'method': 'POST',
            'url': 'https://broker.example/orders',
            'json': self.body,
        }


class StandInPreparedPlacement:
    """An order given a broker and a request, but not yet sent.

    Attributes:
        instrument_id (str): The instrument the order is for.
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request built for it.
        identifier_sent (str): The symbol the request names the instrument by.
        skipped (list): The brokers passed over, which is always none here.
        broker_quantity (int): The quantity the request carries, in the broker's own terms.
    """

    def __init__(self, instrument_id, broker_name, broker_request):
        """Builds the prepared placement.

        Args:
            instrument_id (str): The instrument the order is for.
            broker_name (str): The chosen broker.
            broker_request (StandInBrokerRequest): The request built for it.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.broker_name = broker_name
        self.broker_request = broker_request
        self.identifier_sent = 'SYMBOL'
        self.skipped = []
        self.broker_quantity = broker_request.body['quantity']


class StandInPlacement:
    """Stands in for the engine's placement: serves fixed quotes and positions, chooses Zerodha, and accepts every order, change and cancel.

    Attributes:
        quotes (dict): The live quote for each instrument id.
        positions (dict | None): The unified positions document.
        identities (dict): The identity for each instrument id, where it is not an NSE equity.
        tick_size (str): The tick size every broker agrees on.
        lot_sizes (dict): The lot size for each instrument id, where it is not 1.
        attributes (dict): Every broker's extra fields, such as a freeze quantity.
        refuse_places (bool): Whether the broker refuses new orders.
        cache (object | None): The Redis stand-in an order type reads directly, or None when it reads nothing.
        messages (list): A line for every request the broker received, in order.
        next_number (int): The number the next broker order id is made from.
    """

    def __init__(self, quotes=None, positions=None, tick_size='0.05'):
        """Builds the stand-in.

        Args:
            quotes (dict | None): The live quote for each instrument id.
            positions (dict | None): The unified positions document.
            tick_size (str): The tick size every broker agrees on.

        Returns:
            None: This method returns nothing.
        """
        self.quotes = quotes or {}
        self.positions = positions
        self.identities = {}
        self.tick_size = tick_size
        self.lot_sizes = {}
        self.attributes = {}
        self.refuse_places = False
        self.cache = None
        self.messages = []
        self.next_number = 1

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Answers with the instrument, its quote and the positions.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Whether the quote is wanted.
            needs_positions (bool): Whether the positions are wanted.

        Returns:
            tuple: The instrument (Instrument), the quote (dict | None) and the positions (dict | None).
        """
        identity = self.identities.get(instrument_id)
        if identity is None:
            identity = {
                'segment': 'nse_equities',
            }
        instrument = Instrument(
            instrument_id,
            identity,
            {
                'zerodha': {
                    'order_symbol': 'SYMBOL',
                    'lot_size': self.lot_sizes.get(instrument_id, 1),
                    'tick_size': self.tick_size,
                },
            },
        )
        quote = None
        if needs_quote:
            quote = self.quotes.get(instrument_id)
        positions = None
        if needs_positions:
            positions = self.positions
        return instrument, quote, positions

    def broker_quantity(self, broker_name, instrument_id, units):
        """Converts units into the broker's terms, which for an equity are the units themselves.

        Args:
            broker_name (str): The broker, unused.
            instrument_id (str): The instrument, unused.
            units (int): The quantity in units.

        Returns:
            int: The same quantity.
        """
        del broker_name, instrument_id
        return units

    def broker_attributes(self, instrument_id):
        """Every broker's extra fields for the instrument.

        Args:
            instrument_id (str): The instrument, unused.

        Returns:
            dict: Broker names to their attributes.
        """
        del instrument_id
        return self.attributes

    def prepare(self, order, instrument_id, broker_name=None):
        """Chooses a broker and builds the request, without sending it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument.
            broker_name (str | None): The broker the order must go to, or None for Zerodha.

        Returns:
            StandInPreparedPlacement: The prepared order.
        """
        body = {
            'transaction_type': order.transaction_type,
            'order_type': order.order_type,
            'quantity': order.quantity,
            'price': None if order.price is None else str(order.price),
            'trigger_price': None if order.trigger_price is None else str(order.trigger_price),
        }
        broker_request = StandInBrokerRequest(order.tag, body)
        return StandInPreparedPlacement(
            instrument_id,
            broker_name or 'zerodha',
            broker_request,
        )

    def dry_run_answer(self, prepared_placement, started_at):
        """Answers with the request that would have been sent.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        return {
            'broker': prepared_placement.broker_name,
            'dry_run': True,
            'request': prepared_placement.broker_request.shown(),
        }, 200

    def send(self, prepared_placement, started_at):
        """Sends the order to the stand-in broker, which accepts it unless told to refuse.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        body = prepared_placement.broker_request.body
        described = f"place {body['transaction_type']} {body['quantity']} {body['order_type']}"
        if body['price'] is not None:
            described = f"{described} at {body['price']}"
        if body['trigger_price'] is not None:
            described = f"{described} trigger {body['trigger_price']}"
        if self.refuse_places:
            self.messages.append(f'{described} -> refused')
            return {
                'broker': prepared_placement.broker_name,
                'outcome': 'rejected',
                'order_id': None,
                'status_message': 'the stand-in broker refused the order',
                'broker_response': {
                    'status': 'error',
                },
            }, 400
        order_id = f'2609300000{self.next_number:02d}'
        self.next_number = self.next_number + 1
        self.messages.append(f'{described} -> {order_id}')
        return {
            'broker': prepared_placement.broker_name,
            'outcome': 'accepted',
            'order_id': order_id,
            'status_message': None,
            'broker_response': {
                'status': 'success',
                'data': {
                    'order_id': order_id,
                },
            },
        }, 200

    def cancel(self, broker_name, broker_order_id):
        """Cancels an order at the stand-in broker, which accepts.

        Args:
            broker_name (str): The broker, unused.
            broker_order_id (str): The order.

        Returns:
            StandInAnswer: The answer.
        """
        del broker_name
        self.messages.append(f'cancel {broker_order_id}')
        return StandInAnswer('accepted')

    def modify_leg(
        self,
        broker_name,
        broker_order_id,
        quantity=None,
        price=None,
        trigger_price=None,
    ):
        """Changes an order at the stand-in broker, which accepts.

        Args:
            broker_name (str): The broker, unused.
            broker_order_id (str): The order.
            quantity (int | None): The new quantity.
            price (decimal.Decimal | None): The new price.
            trigger_price (decimal.Decimal | None): The new trigger price.

        Returns:
            StandInAnswer: The answer.
        """
        del broker_name
        described = f'modify {broker_order_id}'
        if quantity is not None:
            described = f'{described} quantity {quantity}'
        if price is not None:
            described = f'{described} price {price}'
        if trigger_price is not None:
            described = f'{described} trigger {trigger_price}'
        self.messages.append(described)
        return StandInAnswer('accepted')


class StandInParentStore:
    """Stands in for the Redis copy of the parents, keeping nothing."""

    def save(self, parent):
        """Accepts a parent without keeping it.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """
        del parent


class BackstopCancelledBeforeTheExitExample:
    """Arms and fires a hidden stop with a backstop by hand.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()

    def runner(self, synthetic):
        """A hidden stop over a short of 40 INFY, built but not run.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            HiddenStop: The runner.
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': 1500,
                'quantity': 40,
                'synthetic': synthetic,
            },
        }
        runner = HiddenStop.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        runner.parent.parameters['tick_size'] = '0.05'
        return runner

    def run(self):
        """Arms, builds and fires the stop, ends a second one whose backstop filled, then prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        runner = self.runner({
            'type': 'hidden_stop',
            'trigger_price': 1520,
            'backstop_price': 1540,
            'backstop_limit_price': 1545,
        })
        trigger, limit = runner.backstop_prices()
        print(f'Backstop: trigger {trigger}, limit {limit}')
        order = runner.read_order(runner.parent.body)
        runner.record_received()
        backstop = runner.arm(order, time.perf_counter())
        print(f"arm: {backstop['outcome']} at {backstop['broker']} as {backstop['order_id']}, parent {runner.parent.state}")

        quote = {
            'last_price': 1521.00,
            'depth': {
                'buy': [
                    {
                        'price': 1520.60,
                        'quantity': 120,
                        'orders': 3,
                    },
                ],
                'sell': [
                    {
                        'price': 1521.00,
                        'quantity': 90,
                        'orders': 2,
                    },
                ],
            },
        }
        view = MarketView(quote, runner.tick_size())
        child = runner.child_order(order, view)
        print(f'child_order: {child.transaction_type} {child.quantity} {child.order_type} at {child.price}')
        runner.fire(child, decimal.Decimal('1521.00'), decimal.Decimal('1520'))
        print('fire sent, in order:')
        for message in self.placement.messages:
            print(f'  {message}')
        print(f'Parent: {runner.parent.state}')

        filled = self.runner({
            'type': 'hidden_stop',
            'trigger_price': 1520,
            'backstop_price': 1540,
            'backstop_limit_price': 1545,
        })
        filled_order = filled.read_order(filled.parent.body)
        filled.record_received()
        filled.arm(filled_order, time.perf_counter())
        backstop_leg = filled.parent.legs[0]
        changes = {
            'leg_state': 'filled',
            'filled_quantity': 40,
        }
        filled.record({
            'event': 'leg_update',
            'parent_state': filled.parent.state,
            'leg_id': backstop_leg.leg_id,
            'leg_role': backstop_leg.role,
            'leg_state': 'filled',
            'filled_quantity': 40,
        })
        filled.on_leg_update(backstop_leg, changes)
        print(f'on_leg_update after the {backstop_leg.role} filled 40: parent {filled.parent.state}, {filled.parent.last_error}')

        half = self.runner({
            'type': 'hidden_stop',
            'trigger_price': 1520,
            'backstop_price': 1540,
        })
        try:
            half.backstop_prices()
        except RefusedRequestError as refusal:
            print(f"Backstop without a limit: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    BackstopCancelledBeforeTheExitExample().run()
