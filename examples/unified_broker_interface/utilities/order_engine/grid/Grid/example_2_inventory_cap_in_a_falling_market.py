"""Shows a grid's inventory cap at work in a falling market, where every buy fills and no sell does.

A grid's weakness is a trending market: in a fall every buy fills and the sells placed above them do not, so the position keeps growing at worse prices. `most_inventory` is the cap. Once the grid's own fills reach it, every resting rung on the side that would make the position bigger is cancelled, and only the exits are left.

This program builds a grid of three levels, five rupees apart, ten shares a rung, around 1,000, with `most_inventory` of 20. The buy at 995 fills and a sell at 1,000 is placed. The buy at 990 fills, which brings the inventory to 20: a sell at 995 is placed, `past_its_cap` becomes true, `adding_side` is BUY, and `stop_adding` cancels the buy still resting at 985. Once the broker confirms that cancel, calling `stop_adding` again finds nothing more to cancel.

Last, it calls `settle`, the step `run` ends with, on a second grid whose every rung the broker refused, which is recorded as `rejected`. The placement is a stand-in that serves the quote, chooses Zerodha and accepts every order and cancel; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. Fills and the cancel's confirmation are recorded as the `leg_update` events the engine's order update follower writes.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/grid/Grid/example_2_inventory_cap_in_a_falling_market.py
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
from unified_broker_interface.utilities.order_engine.grid import (
    Grid,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


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


class InventoryCapInAFallingMarketExample:
    """Fills a grid's buys until the cap stops it adding.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the stand-in placement with RELIANCE at 1,000.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            quotes={
                INSTRUMENT_ID: {
                    'last_price': 1000.00,
                },
            },
        )

    def runner(self):
        """A grid of three levels with a cap of 20, and its intent.

        Returns:
            tuple: The runner (Grid) and its intent (dict).
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'price': 1000,
                'quantity': 10,
                'synthetic': {
                    'type': 'grid',
                    'levels': 3,
                    'step_points': 5,
                    'most_inventory': 20,
                },
            },
        }
        runner = Grid.started(
            intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def update(self, runner, leg, changes):
        """Records an order update on a leg and lets the grid react.

        Args:
            runner (Grid): The grid.
            leg (OrderLeg): The leg.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        event = {
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
        }
        event.update(changes)
        runner.record(event)
        runner.on_leg_update(leg, changes)

    def buy_at(self, runner, price):
        """The resting buy rung at a price.

        Args:
            runner (Grid): The grid.
            price (float): The rung's price.

        Returns:
            OrderLeg: The rung.
        """
        found = None
        for leg in runner.parent.legs:
            if leg.transaction_type == 'BUY' and leg.price == price:
                found = leg
        return found

    def run(self):
        """Fills two buys, shows the cap, and settles a refused grid.

        Returns:
            None: This method returns nothing.
        """
        runner, intent = self.runner()
        runner.run(intent, time.perf_counter())
        for price in (
            995.0,
            990.0,
        ):
            self.update(
                runner,
                self.buy_at(runner, price),
                {
                    'leg_state': 'filled',
                    'filled_quantity': 10,
                },
            )
            print(f'Buy at {price} filled: inventory {runner.inventory()}, past its cap {runner.past_its_cap()}, adding side {runner.adding_side()}')
        print('Sent to the broker, in order:')
        for message in self.placement.messages:
            print(f'  {message}')

        lowest = self.buy_at(runner, 985.0)
        self.update(
            runner,
            lowest,
            {
                'leg_state': 'cancelled',
            },
        )
        print(f'The buy at 985 is confirmed {lowest.state}; stop_adding again cancels {runner.stop_adding(runner.adding_side())}')

        refused, _ = self.runner()
        refused.record_received()
        answers = [
            (
                'BUY',
                decimal.Decimal('995.00'),
                {
                    'outcome': 'rejected',
                    'order_id': None,
                },
                400,
            ),
            (
                'SELL',
                decimal.Decimal('1005.00'),
                {
                    'outcome': 'rejected',
                    'order_id': None,
                },
                400,
            ),
        ]
        body, status = refused.settle(answers, 'zerodha', decimal.Decimal('1000.00'))
        print(f"A grid whose every rung was refused: HTTP {status}, outcome {body['outcome']}, parent {refused.parent.state}")


if __name__ == '__main__':
    InventoryCapInAFallingMarketExample().run()
