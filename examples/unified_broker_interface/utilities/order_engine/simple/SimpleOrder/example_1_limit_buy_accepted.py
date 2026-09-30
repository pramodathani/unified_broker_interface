"""Runs one plain limit buy through the order engine's simplest order type and shows what it records.

A `SimpleOrder` is what every order becomes when the caller asks for no special type: one parent, one leg, and no reaction to anything afterwards. This program builds one from an intent with `SimpleOrder.started`, runs it, and prints the answer the waiting API worker would receive, the events it wrote and the leg it ended up with.

The engine's placement normally reads Redis, chooses a broker and sends the request over HTTP. Here a small stand-in placement takes its place: it always chooses Zerodha, answers every order as accepted with a numbered order id, and keeps the orders it was sent in a list. The event log is the `RecordingEventLog` stand-in from the offline suites, which keeps events in a list instead of writing them to PostgreSQL, and the parent store keeps nothing. So nothing leaves the machine.

Notice the order of the events: `leg_requested` is written before the stand-in broker is called and `leg_answered` after, which is the order a crash between the two relies on. The parent ends as `working`, because a simple order stops once the broker has accepted it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/simple/SimpleOrder/example_1_limit_buy_accepted.py
"""

import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.order_engine.simple import (
    SimpleOrder,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


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
        """The request as the event log keeps it.

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
        self.identifier_sent = 'RELIANCE'
        self.skipped = []


class StandInPlacement:
    """Stands in for the engine's placement: chooses Zerodha and accepts every order.

    Attributes:
        sent (list): Every order sent, as `(broker, transaction_type, quantity, price)`.
        next_number (int): The number the next broker order id is made from.
    """

    def __init__(self):
        """Builds the stand-in with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.sent = []
        self.next_number = 1

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Answers with RELIANCE on the NSE, whose tick size every broker agrees is 0.10.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Unused, since no quote is served.
            needs_positions (bool): Unused, since no positions are served.

        Returns:
            tuple: The instrument (Instrument), no quote and no positions.
        """
        del needs_quote, needs_positions
        instrument = Instrument(
            instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'zerodha': {
                    'order_symbol': 'RELIANCE',
                    'lot_size': 1,
                    'tick_size': '0.10',
                },
            },
        )
        return instrument, None, None

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
            'quantity': order.quantity,
            'price': str(order.price),
        }
        broker_request = StandInBrokerRequest(order.tag, body)
        return StandInPreparedPlacement(
            instrument_id,
            broker_name or 'zerodha',
            broker_request,
        )

    def send(self, prepared_placement, started_at):
        """Sends the order to the stand-in broker, which accepts it.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        body = prepared_placement.broker_request.body
        self.sent.append((
            prepared_placement.broker_name,
            body['transaction_type'],
            body['quantity'],
            body['price'],
        ))
        order_id = f'2609300000{self.next_number:02d}'
        self.next_number = self.next_number + 1
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


class LimitBuyAcceptedExample:
    """Runs one simple limit buy and prints its answer, its events and its leg.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (RecordingEventLog): Where the events are kept.
        runner (SimpleOrder): The order type running the parent.
        intent (dict): The intent the REST API would have written.
    """

    def __init__(self):
        """Builds the runner from an intent for ten RELIANCE shares at 1,402.50.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example')
        self.placement = StandInPlacement()
        self.event_log = RecordingEventLog()
        self.intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': '1402.50',
                'tag': 'morningbuy',
            },
        }
        self.runner = SimpleOrder.started(
            self.intent,
            self.placement,
            self.event_log,
            StandInParentStore(),
            logger,
        )

    def run(self):
        """Runs the order and prints what happened.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f'HTTP status: {status}')
        print(f"Outcome: {body['outcome']}, broker {body['broker']}, order id {body['order_id']}")
        print(f"Answer names this parent: {body['parent_id'] == self.runner.parent.parent_order_id}")
        print(f'Sent to the broker: {self.placement.sent}')
        print('Events recorded:')
        for event in self.event_log.events:
            print(f"  {event['sequence']}. {event['event']} (parent {event['parent_state']})")
        leg = self.runner.parent.legs[0]
        print(f'Parent state: {self.runner.parent.state}')
        print(f'Leg: {leg.role} {leg.transaction_type} {leg.quantity} at {leg.price}, state {leg.state}, tag sent {leg.tag_sent}')


if __name__ == '__main__':
    LimitBuyAcceptedExample().run()
