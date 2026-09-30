"""Hedges a stock purchase with a sold index future, adding whole lots of hedge as the purchase fills.

An `AttachedHedge` places the caller's entry and, each time the entry fills more, works out how much of another instrument is needed to hedge everything filled so far: `ratio` times the filled quantity, on the opposite side, rounded to whole lots of the hedge. Only the lots still missing are sent, so no resting hedge is ever resized.

This program buys 300 shares with a beta of 0.9 against a Nifty future whose lot is 75. The first fill of 100 shares needs 90 units of hedge, which rounds to one lot of 75. When the order fills completely, 270 units are needed, which rounds to four lots, so three more lots are sent. Each hedge is a limit two ticks past the future's best bid.

Fills normally arrive from a broker's order updates; here the program records a `leg_update` event through the runner and then calls `on_leg_update`, as the engine's order update follower does. The placement is a stand-in that serves fixed quotes and lot sizes, chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/attached_hedge/AttachedHedge/example_1_beta_hedge_grows_with_fills.py
"""

import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.order_engine.attached_hedge import (
    AttachedHedge,
)

STOCK_ID = '11111111-1111-5111-8111-000000000001'
FUTURE_ID = '11111111-1111-5111-8111-000000000009'


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


class BetaHedgeGrowsWithFillsExample:
    """Buys a stock with a beta hedge and fills it in two steps.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        intent (dict): The intent the REST API would have written.
        runner (AttachedHedge): The order type running the parent.
    """

    def __init__(self):
        """Builds the runner for 300 shares hedged at a ratio of 0.9.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            quotes={
                FUTURE_ID: {
                    'last_price': 25012.40,
                    'depth': {
                        'buy': [
                            {
                                'price': 25012.00,
                                'quantity': 600,
                                'orders': 4,
                            },
                        ],
                        'sell': [
                            {
                                'price': 25013.10,
                                'quantity': 525,
                                'orders': 3,
                            },
                        ],
                    },
                },
            },
            tick_size='0.10',
        )
        self.placement.lot_sizes[FUTURE_ID] = 75
        self.intent = {
            'intent_id': 'intent-1',
            'instrument_id': STOCK_ID,
            'body': {
                'instrument_id': STOCK_ID,
                'transaction_type': 'BUY',
                'product': 'NRML',
                'order_type': 'LIMIT',
                'price': '1402.50',
                'quantity': 300,
                'synthetic': {
                    'type': 'attached_hedge',
                    'hedge_instrument_id': FUTURE_ID,
                    'ratio': 0.9,
                },
            },
        }
        self.runner = AttachedHedge.started(
            self.intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def fill(self, leg, filled_quantity, state):
        """Records a fill on a leg and lets the order type react, as the order update follower does.

        Args:
            leg (OrderLeg): The leg that filled.
            filled_quantity (int): How much of it has filled in all.
            state (str): The leg's new state, `partially_filled` or `filled`.

        Returns:
            None: This method returns nothing.
        """
        changes = {
            'leg_state': state,
            'filled_quantity': filled_quantity,
        }
        event = {
            'event': 'leg_update',
            'parent_state': self.runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'average_price': 1402.50,
        }
        event.update(changes)
        self.runner.record(event)
        self.runner.on_leg_update(leg, changes)

    def run(self):
        """Places the entry, fills it twice and prints the hedge after each fill.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f"Run: HTTP {status}, outcome {body['outcome']}, parent {self.runner.parent.state}")
        print(f'Hedging in {self.runner.hedge_instrument()} at a ratio of {self.runner.number("ratio")}')
        print(f"Hedge ratio: {self.runner.hedge_ratio()}, hedge lot size at Zerodha: {self.runner.lot_size('zerodha')}")
        entry = self.runner.parent.legs[0]
        self.fill(entry, 100, 'partially_filled')
        print(f'After 100 filled: parent {self.runner.parent.state}, {self.runner.parent.last_error}')
        self.fill(entry, 300, 'filled')
        print(f'After 300 filled: parent {self.runner.parent.state}, {self.runner.parent.last_error}')
        print('Sent to the broker:')
        for message in self.placement.messages:
            print(f'  {message}')
        for leg in self.runner.parent.legs:
            print(f'Leg {leg.role}: {leg.transaction_type} {leg.quantity} of {leg.instrument_id[-4:]}')


if __name__ == '__main__':
    BetaHedgeGrowsWithFillsExample().run()
