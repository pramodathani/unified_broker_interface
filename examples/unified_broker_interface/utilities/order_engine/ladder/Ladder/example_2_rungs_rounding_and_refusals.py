"""Builds a ladder's rungs by hand, showing how prices round to the tick, and the settings it refuses.

`Ladder.rungs` spaces the prices evenly across the range and rounds each one to the tick towards the passive side, so a range that does not divide into ticks gives rungs that rest rather than cross. This program builds four rungs for a sell of 101 ITC from 410.00 to 411.00 with a tick of 0.05: the exact thirds, 410.333 and 410.667, round up to 410.35 and 410.70 because a sell's passive side is up, and the 101 units are shared as 26, 25, 25 and 25.

It also calls the smaller pieces: `price` and `whole` read the range's ends and the step count, and each refuses a bad value with HTTP 400; `rungs` refuses a range whose two ends are the same. Last, `finish` and `answer` turn the rungs' answers into the parent's state and the caller's answer; with one rung refused, the parent is `working` and the answer is `partial` with HTTP 207.

The placement is a stand-in; nothing is sent to it, because the rungs' answers are written out by hand. The event log is the `RecordingEventLog` stand-in and the parent store keeps nothing, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/ladder/Ladder/example_2_rungs_rounding_and_refusals.py
"""

import decimal
import logging

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.ladder import (
    Ladder,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000019'
TICK_SIZE = decimal.Decimal('0.05')


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


class RungsRoundingAndRefusalsExample:
    """Builds rungs by hand and prints the refusals and a combined answer.

    Attributes:
        runner (Ladder): The order type, built but not run.
        order (PlaceOrderRequest): The caller's order.
    """

    def __init__(self):
        """Builds a ladder selling 101 ITC.

        Returns:
            None: This method returns nothing.
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'SELL',
                'product': 'CNC',
                'order_type': 'LIMIT',
                'price': '410.00',
                'quantity': 101,
                'synthetic': {
                    'type': 'ladder',
                    'steps': 4,
                    'from_price': 410,
                    'to_price': 411,
                },
            },
        }
        self.runner = Ladder.started(
            intent,
            StandInPlacement(),
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        self.order = self.runner.read_order(self.runner.parent.body)

    def refusal(self, heading, parameters):
        """Asks for rungs with some parameters and prints the refusal.

        Args:
            heading (str): What is wrong with the parameters.
            parameters (dict): The ladder's parameters.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.runner.rungs(self.order, parameters, TICK_SIZE)
        except RefusedRequestError as refusal:
            print(f"{heading}: HTTP {refusal.status}, {refusal.body['error']}")

    def run(self):
        """Builds the rungs, prints the refusals, and combines two answers.

        Returns:
            None: This method returns nothing.
        """
        rungs = self.runner.rungs(self.order, self.runner.parent.parameters, TICK_SIZE)
        for rung in rungs:
            print(f'Rung: {rung.transaction_type} {rung.quantity} at {rung.price}')
        print(f"price('to_price'): {self.runner.price(self.runner.parent.parameters, 'to_price')}")
        print(f"whole('4', 'steps'): {self.runner.whole('4', 'steps')}")
        try:
            self.runner.whole('four', 'steps')
        except RefusedRequestError as refusal:
            print(f"whole('four'): HTTP {refusal.status}, {refusal.body['error']}")
        try:
            self.runner.price({
                'from_price': -5,
            }, 'from_price')
        except RefusedRequestError as refusal:
            print(f"price(-5): HTTP {refusal.status}, {refusal.body['error']}")
        self.refusal(
            'Both ends the same',
            {
                'steps': 4,
                'from_price': 410,
                'to_price': 410,
            },
        )
        self.refusal(
            'Twenty-five steps',
            {
                'steps': 25,
                'from_price': 410,
                'to_price': 411,
            },
        )

        answers = [
            (
                {
                    'broker': 'zerodha',
                    'order_id': '260930000001',
                    'outcome': 'accepted',
                },
                200,
            ),
            (
                {
                    'broker': 'zerodha',
                    'order_id': None,
                    'outcome': 'rejected',
                },
                400,
            ),
        ]
        self.runner.record_received()
        self.runner.finish(answers)
        body, status = self.runner.answer(answers, 'zerodha', rungs[:2])
        print(f"finish and answer: parent {self.runner.parent.state}, HTTP {status}, outcome {body['outcome']}, rungs {body['rungs']}")


if __name__ == '__main__':
    RungsRoundingAndRefusalsExample().run()
