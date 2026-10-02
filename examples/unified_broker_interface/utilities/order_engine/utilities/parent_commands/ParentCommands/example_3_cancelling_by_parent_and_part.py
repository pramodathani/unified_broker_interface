"""Cancels a bracket plan the engine owns through `ParentCommands`: dry runs of the whole parent and of one part, one part for real, and then the whole parent.

`DELETE /api/orders/cancel` with a `parent_id`, and `DELETE /api/orders/parents`, hand the engine a `cancel_parent` command, which `ParentCommands.cancel_parent` runs on the worker that owns the parent. Without `part` it cancels the whole parent; with `dry_run` it answers through `cancel_parent_dry_run`, naming every leg still resting at a broker as `resting_legs` without sending or changing anything. With `part` it hands the cancel to the plan's own `cancel_part`, so only that part of the plan stops.

This program places a bracket plan, buying ten RELIANCE at 1,000 with a stop at 990 (limit 988) and a target at 1,010, whose entry rests at Zerodha, and stores it under the id `parent-1`. Then, while the entry rests:

1. A dry run of cancelling the whole parent names the resting entry and sends nothing.
2. `cancel_parent_dry_run` is called directly on the parent's order type, and answers the same.
3. A dry run of cancelling the stop part, `root.each_fill.children.0`, answers without changing anything.
4. The stop part is cancelled for real; it has not been sent, so nothing goes to the broker.
5. A part the plan does not have is refused with HTTP 404.
6. The whole parent is cancelled through `run`, with an intent exactly as the engine hands it over, which cancels the resting entry and ends the parent as `cancelled`.
7. Cancelling a part of the finished parent is refused with HTTP 409.

The engine's placement is a small stand-in that always chooses Zerodha and accepts every order and cancel, a stand-in parent store keeps the parents' records in a dictionary, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine. RELIANCE's tick size is 0.10.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_commands/ParentCommands/example_3_cancelling_by_parent_and_part.py
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
from unified_broker_interface.utilities.order_engine.plan import (
    PlanOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_commands import (
    ParentCommands,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'

STOP_PART = 'root.each_fill.children.0'


class BrokerAnswerStandIn:
    """A stand-in for a broker's answer to a change or a cancel.

    Attributes:
        outcome (str): `accepted`, `rejected` or `unknown`.
        status_message (str | None): Why the outcome is not `accepted`.
        response_body (dict): The broker's answer as it sent it.
    """

    def __init__(self, outcome, status_message, response_body):
        """Holds the answer.

        Args:
            outcome (str): `accepted`, `rejected` or `unknown`.
            status_message (str | None): Why the outcome is not `accepted`.
            response_body (dict): The broker's answer as it sent it.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = outcome
        self.status_message = status_message
        self.response_body = response_body


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
        self.identifier_sent = 'RELIANCE'
        self.skipped = []
        self.broker_quantity = broker_request.body['quantity']


class StandInPlacement:
    """Stands in for the engine's placement: chooses Zerodha and accepts every order and every cancel.

    Attributes:
        messages (list): A line for every order and cancel the broker received, in order.
        next_number (int): The number the next broker order id is made from.
    """

    def __init__(self):
        """Builds the stand-in with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.messages = []
        self.next_number = 1

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Answers with RELIANCE on the NSE, whose tick size every broker agrees is 0.10, no quote and no open positions.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Unused, since no quote is served.
            needs_positions (bool): Unused, since the positions are always empty.

        Returns:
            tuple: The instrument (Instrument), no quote and the positions (dict).
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
        return instrument, None, {
            'net': [],
        }

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
        """Sends the order to the stand-in broker, which accepts it.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        body = prepared_placement.broker_request.body
        order_id = f'2609300000{self.next_number:02d}'
        self.next_number = self.next_number + 1
        described = f"place {body['transaction_type']} {body['quantity']} {body['order_type']}"
        if body['price'] is not None:
            described = f"{described} at {body['price']}"
        if body['trigger_price'] is not None:
            described = f"{described} trigger {body['trigger_price']}"
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
        """Accepts a cancel of one order.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's order id.

        Returns:
            BrokerAnswerStandIn: An accepted answer.
        """
        self.messages.append(f'cancel {broker_name} {broker_order_id}')
        response_body = {
            'status': 'success',
            'data': {
                'order_id': broker_order_id,
            },
        }
        return BrokerAnswerStandIn('accepted', None, response_body)


class DictionaryParentStore:
    """A stand-in for the parent store that keeps parent records in a dictionary.

    Attributes:
        documents (dict): Each parent order id to its record.
    """

    def __init__(self, documents):
        """Builds the store.

        Args:
            documents (dict): Each parent order id to its record.

        Returns:
            None: This method returns nothing.
        """
        self.documents = documents

    def parent(self, parent_order_id):
        """One parent's record.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            dict | None: The record, or None when there is none.
        """
        return self.documents.get(parent_order_id)

    def save(self, parent):
        """Writes one parent's record.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """
        self.documents[parent.parent_order_id] = parent.document()


class CancellingByParentAndPartExample:
    """Places a bracket plan and cancels it by part and as a whole through the parent commands.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        parent_store (DictionaryParentStore): The stand-in parent store.
        event_log (RecordingEventLog): Where the events are kept.
        commands (ParentCommands): The commands being shown.
    """

    def __init__(self):
        """Builds the commands over an empty parent store.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()
        self.parent_store = DictionaryParentStore({})
        self.event_log = RecordingEventLog()
        self.commands = ParentCommands(
            self.placement,
            self.event_log,
            self.parent_store,
            logging.getLogger('example'),
            None,
        )

    def place_bracket(self):
        """Places a bracket plan for ten RELIANCE at 1,000.00 under the id `parent-1`, whose entry rests.

        Returns:
            None: This method returns nothing.
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': '1000.00',
                'synthetic': {
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'bracket': {
                                        'stop_price': 990,
                                        'stop_limit_price': 988,
                                        'target_price': 1010,
                                    },
                                },
                            ],
                        },
                    },
                },
            },
        }
        runner = PlanOrder.started(
            intent,
            self.placement,
            self.event_log,
            self.parent_store,
            logging.getLogger('example'),
        )
        runner.parent.parent_order_id = 'parent-1'
        body, status = runner.run(intent, time.perf_counter())
        print(f"Placed: HTTP {status}, {body['outcome']}, entry {body['legs'][0]['path']} order id {body['legs'][0]['order_id']}")

    def show(self, label, arguments):
        """Runs one `cancel_parent` and prints the answer or the refusal.

        Args:
            label (str): What is being asked.
            arguments (dict): The command's arguments.

        Returns:
            None: This method returns nothing.
        """
        try:
            body, status = self.commands.cancel_parent(arguments)
        except RefusedRequestError as error:
            print(f"{label}: HTTP {error.status}, {error.body['error']}")
            return
        print(f'{label}: HTTP {status}, {body}')

    def run(self):
        """Places the bracket, runs the dry runs and cancels, and prints what was sent and what the store holds.

        Returns:
            None: This method returns nothing.
        """
        self.place_bracket()
        self.show(
            'A dry run of cancelling the whole parent',
            {
                'parent_id': 'parent-1',
                'dry_run': True,
            },
        )
        runner = self.commands.runner_for('parent-1')
        body, status = self.commands.cancel_parent_dry_run(runner)
        print(f"cancel_parent_dry_run called directly: HTTP {status}, resting legs {body['resting_legs']}")
        self.show(
            'A dry run of cancelling the stop part',
            {
                'parent_id': 'parent-1',
                'part': STOP_PART,
                'dry_run': True,
            },
        )
        self.show(
            'The stop part cancelled',
            {
                'parent_id': 'parent-1',
                'part': STOP_PART,
            },
        )
        stored_parts = self.parent_store.documents['parent-1']['parameters']['parts']
        print(f"  The stored stop part's record: {stored_parts[STOP_PART]}")
        self.show(
            'A part the plan does not have',
            {
                'parent_id': 'parent-1',
                'part': 'root.nowhere',
            },
        )
        cancel_parent_intent = {
            'command': 'cancel_parent',
            'body': {
                'parent_id': 'parent-1',
            },
        }
        body, status = self.commands.run(cancel_parent_intent)
        print(f"The whole parent cancelled: HTTP {status}, state {body['state']}, {len(body['cancelled_legs'])} leg cancelled")
        self.show(
            'The stop part cancelled once the parent is cancelled',
            {
                'parent_id': 'parent-1',
                'part': STOP_PART,
            },
        )
        print('Sent to the broker, in order:')
        for message in self.placement.messages:
            print(f'  {message}')
        print(f"Stored parent: {self.parent_store.documents['parent-1']['state']}")


if __name__ == '__main__':
    CancellingByParentAndPartExample().run()
