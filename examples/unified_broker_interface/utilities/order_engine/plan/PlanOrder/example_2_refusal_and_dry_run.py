"""Shows a plan the engine refuses, with every problem listed at once, and a dry run of a plan it accepts.

A `PlanOrder` is the order type the composable synthetic orders are built on. A plan is read and checked in full before anything is recorded or sent, and a plan with problems is refused with HTTP 400 and all of them in `problems`, each naming the part's path and the rule it breaks. This program sends one plan with three problems, then a dry run of a valid plan, which answers with the broker request that would be sent and the plan as it would run, every default written out.

The engine's placement is a small stand-in that always chooses Zerodha, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine. Notice that neither run records an event or sends an order.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/plan/PlanOrder/example_2_refusal_and_dry_run.py
"""

import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.order_engine.plan import (
    PlanOrder,
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


class RefusalAndDryRunExample:
    """Sends a plan with three problems, then a dry run of a valid plan, and prints both answers.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (RecordingEventLog): Where the events are kept.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()
        self.event_log = RecordingEventLog()

    def intent(self, plan, dry_run):
        """The intent for ten RELIANCE shares at 1,402.50, described by a plan.

        Args:
            plan (object): The `plan` object.
            dry_run (bool): Whether the order is a dry run.

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
                'synthetic': {
                    'type': 'plan',
                    'plan': plan,
                },
            },
        }

    def runner(self, intent):
        """Builds the order type for one intent.

        Args:
            intent (dict): The intent.

        Returns:
            PlanOrder: The runner.
        """
        return PlanOrder.started(
            intent,
            self.placement,
            self.event_log,
            StandInParentStore(),
            logging.getLogger('example'),
        )

    def run(self):
        """Sends both plans and prints what the engine answered.

        Returns:
            None: This method returns nothing.
        """
        faulty = self.intent(
            {
                'order': {
                    'side': 'buy',
                    'presets': [
                        {
                            'grid': {},
                        },
                        {
                            'simple': {
                                'broker': 'zerodha',
                            },
                        },
                    ],
                },
            },
            False,
        )
        try:
            self.runner(faulty).run(faulty, time.perf_counter())
        except RefusedRequestError as refusal:
            print(f"Refused with HTTP {refusal.status}: {refusal.body['error']}")
            for problem in refusal.body['problems']:
                print(f"  {problem['path']} [{problem['rule']}]: {problem['message']}")
        valid = self.intent(
            {
                'order': {
                    'presets': [
                        {
                            'simple': {},
                        },
                    ],
                },
            },
            True,
        )
        body, status = self.runner(valid).run(valid, time.perf_counter())
        print(f'Dry run: HTTP {status}, broker {body["broker"]}')
        print(f"  Request: {body['request']['json']}")
        print(f"  Plan as it would run: {body['plan']}")
        print(f'Events recorded: {len(self.event_log.events)}, orders sent: {len(self.placement.sent)}')


if __name__ == '__main__':
    RefusalAndDryRunExample().run()
