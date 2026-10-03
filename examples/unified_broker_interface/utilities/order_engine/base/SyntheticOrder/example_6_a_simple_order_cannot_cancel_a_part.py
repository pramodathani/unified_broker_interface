"""Places a simple order and asks it to cancel a part, which only a plan order has, so `SyntheticOrder.cancel_part` refuses with HTTP 409.

`DELETE /api/orders/cancel` with a parent's id and a `part` reaches `cancel_part` on the parent's order type. A plan order describes itself as a tree of parts and can cancel one of them; a `simple` order, the only other kind the engine runs, is one order sent at once, so the base class refuses whatever path is named, whether the cancel is a dry run or not. Such a parent is cancelled whole instead, by leaving `part` out. This program places a simple limit buy of ten RELIANCE at 1000, asks for three part cancels, and shows that each is refused, and that the refusals recorded nothing and sent nothing beyond the order itself; the parent stays as it was placed.

The engine's placement is a small stand-in that always chooses Zerodha and accepts every order, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/base/SyntheticOrder/example_6_a_simple_order_cannot_cancel_a_part.py
"""

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


class ASimpleOrderCannotCancelAPartExample:
    """Places a simple order and asks it for part cancels.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (RecordingEventLog): Where the events are kept.
        intent (dict): The intent the REST API would have written.
        runner (SimpleOrder): The order type running the parent.
    """

    def __init__(self):
        """Builds the runner from an intent to buy ten RELIANCE with a limit at 1000.

        Returns:
            None: This method returns nothing.
        """
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
                'price': 1000,
                'quantity': 10,
                'synthetic': {
                    'type': 'simple',
                },
            },
        }
        self.runner = SimpleOrder.started(
            self.intent,
            self.placement,
            self.event_log,
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def show(self, label, path, dry_run):
        """Asks for one part to be cancelled and prints the answer or the refusal.

        Args:
            label (str): What is being asked.
            path (str): The part's path.
            dry_run (bool): Whether only to check it.

        Returns:
            None: This method returns nothing.
        """
        try:
            body, status = self.runner.cancel_part(path, dry_run)
        except RefusedRequestError as error:
            print(f"{label}: HTTP {error.status}, {error.body['error']}")
            return
        print(f'{label}: HTTP {status}, {body}')

    def run(self):
        """Places the order and asks for the part cancels.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f"Answer: HTTP {status}, {body['outcome']}: {body['status_message']}")
        events_before = len(self.event_log.events)
        self.show('A dry run cancelling part root', 'root', True)
        self.show('Part root cancelled', 'root', False)
        self.show('Part root.first cancelled', 'root.first', False)
        print(f'Events recorded by the refusals: {len(self.event_log.events) - events_before}, orders sent: {len(self.placement.sent)}')
        print(f'Parent: {self.runner.parent.state}')


if __name__ == '__main__':
    ASimpleOrderCannotCancelAPartExample().run()
