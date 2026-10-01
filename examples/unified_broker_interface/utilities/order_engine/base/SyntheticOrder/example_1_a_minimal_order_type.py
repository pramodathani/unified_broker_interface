"""Writes a minimal order type on `SyntheticOrder` and runs it, to show what the base class gives every type.

A `SyntheticOrder` subclass sets `SYNTHETIC_TYPE` and implements `run`. Everything else is shared: `started` builds the runner and its parent from an intent, `read_order` validates the caller's body, `concrete_order` turns a price reference into a real price, `remember_tick_size` keeps the instrument's tick size on the parent, `record_received`, `record_state` and `record` write events in order and apply them to the parent, `save` writes the parent to Redis, and `place_leg` is the only way an order reaches a broker. The base class's own `run` refuses to run, because it does not know what to place.

This program defines `MidPriceOrder`, which places one limit at the price a `price_reference` of `mid` works out to, and runs it for 10 RELIANCE on a book bid 1,000.00 and offered 1,000.20. It then prints what the shared helpers answer: `json_number` for a price, `closes_position` for an entry and a stop, `now`'s timezone, `chosen_broker` before and after a leg exists, and `release_daily_place`, which does nothing without risk gates. It also records a leg by hand with `record_and_send_leg`, the step `place_leg` ends with, after the placement has prepared it.

The placement is a stand-in that serves the book, chooses Zerodha and accepts every order; the event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/base/SyntheticOrder/example_1_a_minimal_order_type.py
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
from unified_broker_interface.utilities.order_engine.base import (
    SyntheticOrder,
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


class MidPriceOrder(SyntheticOrder):
    """One limit order at whatever price the caller's price reference works out to, and nothing more.

    Attributes:
        SYNTHETIC_TYPE (str): The name this example type goes by.
    """

    SYNTHETIC_TYPE = 'mid_price_example'

    def run(self, intent, started_at):
        """Places the order at the price its reference works out to.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        self.remember_tick_size(order)
        self.record_received()
        self.save()
        body, status, _ = self.place_leg('entry', order, started_at)
        if body.get('outcome') == 'accepted':
            self.record_state('working', None)
        else:
            self.record_state('rejected', body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        return body, status


class AMinimalOrderTypeExample:
    """Runs the example type and prints what the base class provided.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        intent (dict): The intent the REST API would have written.
    """

    def __init__(self):
        """Builds the stand-in placement and an intent priced by the mid.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement(
            quotes={
                INSTRUMENT_ID: {
                    'last_price': 1000.10,
                    'depth': {
                        'buy': [
                            {
                                'price': 1000.00,
                                'quantity': 100,
                                'orders': 1,
                            },
                        ],
                        'sell': [
                            {
                                'price': 1000.20,
                                'quantity': 100,
                                'orders': 1,
                            },
                        ],
                    },
                },
            },
        )
        self.intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price_reference': {
                    'kind': 'mid',
                },
                'synthetic': {
                    'type': 'mid_price_example',
                },
            },
        }

    def runner(self, order_class):
        """A runner of a given class for the intent.

        Args:
            order_class (type): `SyntheticOrder` or a subclass.

        Returns:
            SyntheticOrder: The runner.
        """
        return order_class.started(
            self.intent,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def run(self):
        """Runs the base class and the example type, and prints the shared helpers.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.runner(SyntheticOrder).run(self.intent, time.perf_counter())
        except NotImplementedError as error:
            print(f'SyntheticOrder.run: NotImplementedError, {error}')

        runner = self.runner(MidPriceOrder)
        order = runner.read_order(runner.parent.body)
        print(f"read_order: {order.order_type} {order.quantity}, price {order.price}, price_reference {order.price_reference}")
        concrete = runner.concrete_order(order)
        print(f'concrete_order: price {concrete.price}, price_reference {concrete.price_reference}')
        print(f'chosen_broker before any leg: {runner.chosen_broker()}')
        body, status = runner.run(self.intent, time.perf_counter())
        print(f"Run: HTTP {status}, outcome {body['outcome']}, order {body['order_id']}, parent {runner.parent.state}, tick size kept {runner.tick_size()}")
        print(f'chosen_broker after it: {runner.chosen_broker()}')
        events = []
        for event in runner.event_log.events:
            events.append(event['event'])
        print(f'Events: {events}')

        print(f"json_number(Decimal('1000.10')): {runner.json_number(decimal.Decimal('1000.10'))}, json_number(None): {runner.json_number(None)}")
        print(f"closes_position('entry'): {runner.closes_position('entry')}, closes_position('stop'): {runner.closes_position('stop')}")
        print(f'now() is timezone-aware in {runner.now().tzname()}')
        runner.release_daily_place()
        print('release_daily_place without gates: nothing to release')

        prepared = self.placement.prepare(concrete, INSTRUMENT_ID, 'zerodha')
        body, status, leg_id = runner.record_and_send_leg('entry', concrete, prepared, None, INSTRUMENT_ID)
        print(f"record_and_send_leg: HTTP {status}, {body['outcome']}, leg {leg_id.rsplit(':', 1)[1]} of the parent")
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg_id,
            'leg_role': 'entry',
            'leg_state': 'filled',
            'filled_quantity': 10,
            'average_price': 1000.10,
        })
        leg = runner.parent.legs[-1]
        print(f'record: a fill written as the order update follower writes it leaves leg 2 {leg.state} with {leg.filled_quantity}, sequence {runner.parent.sequence}')
        print(f'Sent to the broker: {self.placement.messages}')
        print(f'carries_parent_overnight: a type that does not set CARRIES_OVERNIGHT is not rebuilt from before today: {MidPriceOrder.carries_parent_overnight(runner.parent)}')


if __name__ == '__main__':
    AMinimalOrderTypeExample().run()
