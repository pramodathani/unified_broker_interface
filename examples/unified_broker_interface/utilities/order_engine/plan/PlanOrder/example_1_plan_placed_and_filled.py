"""Runs a plan of one simple order through the order engine, fills it, and shows the plan's part finishing; then cancels a second one.

A `PlanOrder` is the order type the composable synthetic orders are built on. Its `synthetic.plan` describes the order as a tree of parts; so far a plan can hold one order built from the `simple` preset. This program places such a plan, then feeds the engine a fill for the whole quantity, and prints the answer, the broker order, the state kept for the plan's `root` part, and the events recorded.

The engine's placement is a small stand-in that always chooses Zerodha and accepts every order, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine. The fill is recorded as the order update follower would record it, and then handed to the order type.

Notice that the broker order's role is `root`, the path of the part that placed it, and that the part's state is recorded with a `parameters_changed` event each time it changes, which is what lets recovery rebuild it after a restart.

The second plan is cancelled by the caller before anything fills. The parent moves to `cancelling`, the broker confirms the cancel, and `finish_cancelling` ends the parent and marks the root part done as `cancelled`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/plan/PlanOrder/example_1_plan_placed_and_filled.py
"""

import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
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


class PlanPlacedAndFilledExample:
    """Places a plan of one simple order, fills it, and prints what the plan recorded.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (RecordingEventLog): Where the events are kept.
        runner (PlanOrder): The order type running the parent.
        intent (dict): The intent the REST API would have written.
    """

    def __init__(self):
        """Builds the runner from an intent for ten RELIANCE shares at 1,402.50, described as a plan.

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
                'synthetic': {
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'simple': {},
                                },
                            ],
                        },
                    },
                },
            },
        }
        self.runner = PlanOrder.started(
            self.intent,
            self.placement,
            self.event_log,
            StandInParentStore(),
            logger,
        )

    def cancel_second_plan(self):
        """Places a second plan like the first, cancels it before anything fills, and prints how it ends.

        Returns:
            None: This method returns nothing.
        """
        runner = PlanOrder.started(
            dict(self.intent, intent_id='intent-2'),
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        runner.run(self.intent, time.perf_counter())
        leg = runner.parent.legs[0]
        runner.record_state('cancelling', 'the caller cancelled the plan')
        runner.record({
            'event': 'leg_update',
            'parent_state': runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'leg_state': 'cancelled',
            'filled_quantity': 0,
        })
        ended = runner.finish_cancelling()
        print(f'Second plan ended by finish_cancelling: {ended}')
        print(f"Second plan's parts: {runner.parent.parameters['parts']}")
        print(f'Second plan: {runner.parent.state}')

    def run(self):
        """Places the plan, fills its order, and prints what happened.

        Returns:
            None: This method returns nothing.
        """
        body, status = self.runner.run(self.intent, time.perf_counter())
        print(f'HTTP status: {status}')
        print(f"Outcome: {body['outcome']}, broker {body['broker']}, order id {body['order_id']}")
        leg = self.runner.parent.legs[0]
        print(f'Broker order: role {leg.role}, {leg.transaction_type} {leg.quantity}, state {leg.state}')
        print(f"Parts after placing: {self.runner.parent.parameters['parts']}")
        print(f'Parent after placing: {self.runner.parent.state}')
        self.runner.record({
            'event': 'leg_update',
            'parent_state': self.runner.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'leg_state': 'filled',
            'filled_quantity': 10,
            'average_price': 1402.5,
        })
        self.runner.on_leg_update(
            leg,
            {
                'leg_state': 'filled',
                'filled_quantity': 10,
            },
        )
        print(f"Parts after the fill: {self.runner.parent.parameters['parts']}")
        print(f'Parent after the fill: {self.runner.parent.state}')
        print('Events recorded:')
        for event in self.event_log.events:
            print(f"  {event['sequence']}. {event['event']}: {event.get('status_message')}")
        self.cancel_second_plan()


if __name__ == '__main__':
    PlanPlacedAndFilledExample().run()
