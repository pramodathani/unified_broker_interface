"""Shows a simple order's two other endings: a dry run that records nothing, and an order the broker refuses.

A caller can set `dry_run` to see the request an order would send without sending it. A `SimpleOrder` answers that from the prepared request and writes no event at all, because no order exists that recovery would have to find. When the broker refuses a real order, the parent is recorded and ends as `rejected` rather than `working`.

The stand-in placement here answers a dry run with the request it built, and answers every real order with a refusal whose message looks like one Zerodha sends when margin is short. The event log is the `RecordingEventLog` stand-in from the offline suites and the parent store keeps nothing, so nothing leaves the machine.

Notice that the dry run leaves the event log empty and the parent with no legs, while the refused order leaves four events, a leg in `rejected` and the broker's message on the parent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/simple/SimpleOrder/example_2_dry_run_and_rejection.py
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


class RefusingPlacement:
    """Stands in for the engine's placement: chooses Zerodha, answers dry runs, and refuses every real order.

    Attributes:
        sent (int): How many orders were sent to the stand-in broker.
    """

    def __init__(self):
        """Builds the stand-in with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.sent = 0

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
        """Sends the order to the stand-in broker, which refuses it.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        self.sent = self.sent + 1
        message = 'Insufficient funds. Required margin is 14025.00 but available margin is 3100.00.'
        return {
            'broker': prepared_placement.broker_name,
            'outcome': 'rejected',
            'order_id': None,
            'status_message': message,
            'broker_response': {
                'status': 'error',
                'error_type': 'InputException',
                'message': message,
            },
        }, 400


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


class DryRunAndRejectionExample:
    """Runs the same limit buy once as a dry run and once for real, and prints both endings.

    Attributes:
        logger (logging.Logger): The logger handed to the order type.
        placement (RefusingPlacement): The stand-in placement.
    """

    def __init__(self):
        """Builds the logger and the stand-in placement.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('example')
        self.placement = RefusingPlacement()

    def intent(self, dry_run):
        """An intent for ten RELIANCE shares at 1,402.50.

        Args:
            dry_run (bool): Whether the caller asked for a dry run.

        Returns:
            dict: The intent.
        """
        return {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': '1402.50',
                'dry_run': dry_run,
            },
        }

    def run(self):
        """Runs both orders and prints what each left behind.

        Returns:
            None: This method returns nothing.
        """
        dry_run_intent = self.intent(True)
        dry_run_log = RecordingEventLog()
        dry_runner = SimpleOrder.started(
            dry_run_intent,
            self.placement,
            dry_run_log,
            StandInParentStore(),
            self.logger,
        )
        body, status = dry_runner.run(dry_run_intent, time.perf_counter())
        print('Dry run:')
        print(f'  HTTP status {status}, answer {body}')
        print(f'  Events recorded: {len(dry_run_log.events)}, legs: {len(dry_runner.parent.legs)}')

        real_intent = self.intent(False)
        real_log = RecordingEventLog()
        runner = SimpleOrder.started(
            real_intent,
            self.placement,
            real_log,
            StandInParentStore(),
            self.logger,
        )
        body, status = runner.run(real_intent, time.perf_counter())
        print('Real order:')
        print(f"  HTTP status {status}, outcome {body['outcome']}")
        print(f'  Orders the broker was sent: {self.placement.sent}')
        event_names = []
        for event in real_log.events:
            event_names.append(event['event'])
        print(f'  Events recorded: {event_names}')
        print(f'  Leg state: {runner.parent.legs[0].state}')
        print(f'  Parent state: {runner.parent.state}')
        print(f'  Why: {runner.parent.last_error}')


if __name__ == '__main__':
    DryRunAndRejectionExample().run()
