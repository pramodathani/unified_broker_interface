"""Shows a square-off limited to named instruments, one on a product with nothing open, and the setting it refuses.

A `SquareOff` closes every position on its `product`, intraday by default, unless `instrument_ids` names a set, in which case only those are closed. `product` is on the vocabulary the positions document uses, such as `intraday`, `delivery` or `carryforward`, which is not the vocabulary orders are sent with.

This program schedules two square-offs at 15:10 on Thursday 1 October 2026 and ticks each at that time:

1. One limited to INFY closes the short of 15 INFY and leaves the long of 20 RELIANCE alone.
2. One on the `delivery` product finds nothing open there, so it sends nothing and the parent is `completed`.

Last, `instrument_ids` given as a single id instead of a list is refused by `wanted_instruments` with HTTP 400.

`run` reads the time from the engine's `Moments` clock, so the program replaces that clock, in the `square_off` module, with a stand-in stopped at 14:00 that Thursday; every tick is a fixed moment. A stand-in cache answers that no orders are resting, and the stand-in placement serves the positions and quotes, chooses Zerodha and accepts every order. The event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine. The trading calendar is read from the calendar files kept in the repository.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/square_off/SquareOff/example_2_named_instruments_and_nothing_to_close.py
"""

import datetime
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
from unified_broker_interface.utilities.order_engine import square_off
from unified_broker_interface.utilities.order_engine.square_off import (
    SquareOff,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    INDIA,
    Moments,
)

RELIANCE = '11111111-1111-5111-8111-000000000001'
INFY = '11111111-1111-5111-8111-000000000002'
ASKED_AT = datetime.datetime(2026, 10, 1, 14, 0, tzinfo=INDIA)
CLOSE_AT = datetime.datetime(2026, 10, 1, 15, 10, tzinfo=INDIA)


class FixedMoments(Moments):
    """The engine's clock, stopped at 14:00 on Thursday 1 October 2026."""

    def now(self):
        """The fixed moment.

        Returns:
            datetime.datetime: 14:00 on 1 October 2026, in India.
        """
        return ASKED_AT


class EmptyOrderUpdatesCache:
    """Stands in for Redis, with no order resting anywhere."""

    def hgetall(self, key):
        """Reads the whole of one hash, which is always empty.

        Args:
            key (str): The key, unused.

        Returns:
            dict: An empty hash.
        """
        del key
        return {}


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


class NamedInstrumentsAndNothingToCloseExample:
    """Runs two square-offs and prints a refusal."""

    def runner(self, synthetic):
        """A square-off with its own stand-in placement, and its intent.

        Args:
            synthetic (dict): The order type's parameters.

        Returns:
            tuple: The runner (SquareOff) and its intent (dict).
        """
        placement = StandInPlacement(
            quotes={
                INFY: {
                    'last_price': 1488.00,
                    'depth': {
                        'buy': [
                            {
                                'price': 1487.95,
                                'quantity': 300,
                                'orders': 3,
                            },
                        ],
                        'sell': [
                            {
                                'price': 1488.05,
                                'quantity': 300,
                                'orders': 3,
                            },
                        ],
                    },
                },
            },
            positions={
                'net': [
                    {
                        'instrument_id': RELIANCE,
                        'product': 'intraday',
                        'quantity': 20,
                    },
                    {
                        'instrument_id': INFY,
                        'product': 'intraday',
                        'quantity': -15,
                    },
                ],
                'day': [],
            },
        )
        placement.cache = EmptyOrderUpdatesCache()
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': RELIANCE,
            'body': {
                'instrument_id': RELIANCE,
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'MARKET',
                'quantity': 1,
                'synthetic': synthetic,
            },
        }
        runner = SquareOff.started(
            intent,
            placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        return runner, intent

    def square_off(self, heading, synthetic):
        """Schedules one square-off, ticks it at 15:10 and prints what it did.

        Args:
            heading (str): What the square-off is.
            synthetic (dict): The order type's parameters.

        Returns:
            None: This method returns nothing.
        """
        runner, intent = self.runner(synthetic)
        runner.run(intent, time.perf_counter())
        runner.on_clock_tick(CLOSE_AT.timestamp())
        print(f'{heading}: product {runner.product()}, instruments {runner.wanted_instruments()}')
        print(f'  sent {runner.placement.messages}')
        print(f'  parent {runner.parent.state}, {runner.parent.last_error}')

    def run(self):
        """Runs the two square-offs and prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        square_off.Moments = FixedMoments
        self.square_off(
            'Only INFY',
            {
                'type': 'square_off',
                'at_time': '15:10',
                'instrument_ids': [
                    INFY,
                ],
            },
        )
        self.square_off(
            'The delivery product',
            {
                'type': 'square_off',
                'at_time': '15:10',
                'product': 'delivery',
            },
        )
        careless, _ = self.runner({
            'type': 'square_off',
            'at_time': '15:10',
            'instrument_ids': INFY,
        })
        try:
            careless.wanted_instruments()
        except RefusedRequestError as refusal:
            print(f"instrument_ids as a single id: HTTP {refusal.status}, {refusal.body['error']}")


if __name__ == '__main__':
    NamedInstrumentsAndNothingToCloseExample().run()
