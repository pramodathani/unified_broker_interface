"""Shows the changes `ParentCommands` refuses, a parent cancel the broker only partly accepts, and flatten halting a parent.

A command that cannot be carried out raises `RefusedRequestError`, whose body and status are what the route answers the caller with. This program runs five such cases and prints each refusal: a command the engine does not know (400), a parent it does not hold (404), a leg that has already filled (409), a price change to a `simple` parent, which holds no order of its own to change (409), and a cancel of a parent that has already finished (409).

It then cancels a `simple` parent whose broker refuses the cancel. The leg may still be live, so the parent is not called cancelled; it becomes `cancelling` and the answer's status is 207. Next it halts an open parent the way `POST /api/orders/flatten` does, which ends it as `cancelled` without touching its legs, and halts a parent that does not exist, which quietly does nothing. Finally it calls `runner_for`, `leg_to_change`, `answered` and `decimal_or_none` directly to show the pieces the commands are built from.

A stand-in placement answers every cancel with the refusal Zerodha sends for an order it is still processing, without calling a broker. A stand-in parent store keeps the parents' records in a dictionary, and a stand-in event log keeps the events. The program needs no broker, no data store and no network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_commands/ParentCommands/example_2_refusals_and_halting.py
"""

import logging

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_commands import (
    ParentCommands,
)

INFY = '11111111-1111-5111-8111-000000000001'


class BrokerAnswerStandIn:
    """A stand-in for a broker's answer to a cancel.

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


class RefusingPlacement:
    """A stand-in for the engine's placement whose broker refuses every cancel.

    Attributes:
        sent (list): What was sent, one line per request.
    """

    def __init__(self):
        """Builds the placement with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.sent = []

    def cancel(self, broker_name, broker_order_id):
        """Answers a cancel with the refusal Zerodha sends for an order it is still processing.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's order id.

        Returns:
            BrokerAnswerStandIn: A rejected answer.
        """
        self.sent.append(f'cancel {broker_name} {broker_order_id}')
        message = 'Order cannot be cancelled as it is being processed. Try later.'
        response_body = {
            'status': 'error',
            'message': message,
            'error_type': 'OrderException',
        }
        return BrokerAnswerStandIn('rejected', message, response_body)


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


class ListEventLog:
    """A stand-in for the event log that keeps events in a list.

    Attributes:
        events (list): Every event recorded.
    """

    def __init__(self):
        """Builds an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []

    def record(self, event):
        """Keeps one event.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        self.events.append(event)


class RefusalsAndHaltingExample:
    """Runs refused commands, a partly refused cancel and two halts, and prints each result.

    Attributes:
        placement (RefusingPlacement): The stand-in placement.
        parent_store (DictionaryParentStore): The stand-in parent store.
        commands (ParentCommands): The commands being shown.
    """

    def __init__(self):
        """Builds the commands over four stored parents.

        Returns:
            None: This method returns nothing.
        """
        documents = {
            'parent-filled': self.document('parent-filled', 'completed', 'filled', '250930000201'),
            'parent-done': self.document('parent-done', 'cancelled', 'cancelled', '250930000202'),
            'parent-stuck': self.document('parent-stuck', 'working', 'acknowledged', '250930000203'),
            'parent-open': self.document('parent-open', 'working', 'acknowledged', '250930000204'),
        }
        self.placement = RefusingPlacement()
        self.parent_store = DictionaryParentStore(documents)
        self.commands = ParentCommands(
            self.placement,
            ListEventLog(),
            self.parent_store,
            logging.getLogger('example'),
            None,
        )

    def document(self, parent_order_id, parent_state, leg_state, broker_order_id):
        """Builds the record of a `simple` parent with one Zerodha buy limit order.

        Args:
            parent_order_id (str): The parent's id.
            parent_state (str): The parent's state.
            leg_state (str): The leg's state.
            broker_order_id (str): Zerodha's id for the order.

        Returns:
            dict: The record.
        """
        return {
            'parent_order_id': parent_order_id,
            'synthetic_type': 'simple',
            'state': parent_state,
            'instrument_id': INFY,
            'body': {},
            'parameters': {},
            'legs': [
                {
                    'leg_id': f'{parent_order_id}-1',
                    'role': 'entry',
                    'state': leg_state,
                    'instrument_id': INFY,
                    'broker': 'zerodha',
                    'broker_order_id': broker_order_id,
                    'transaction_type': 'BUY',
                    'product': 'MIS',
                    'order_type': 'LIMIT',
                    'quantity': 10,
                    'price': 1498.0,
                },
            ],
        }

    def refused(self, label, intent):
        """Runs one command that is expected to be refused, and prints the refusal.

        Args:
            label (str): What the case shows.
            intent (dict): The intent carrying the command.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.commands.run(intent)
        except RefusedRequestError as refusal:
            print(f'{label}: {refusal.status} {refusal.body["error"]}')

    def run(self):
        """Runs every case and prints the results.

        Returns:
            None: This method returns nothing.
        """
        unknown_command = {
            'command': 'split_leg',
            'body': {},
        }
        self.refused('Unknown command', unknown_command)
        unknown_parent = {
            'command': 'cancel_parent',
            'body': {
                'parent_id': 'parent-missing',
            },
        }
        self.refused('Unknown parent', unknown_parent)
        filled_leg = {
            'command': 'cancel_leg',
            'body': {
                'parent_id': 'parent-filled',
                'broker': 'zerodha',
                'order_id': '250930000201',
            },
        }
        self.refused('Filled leg', filled_leg)
        held_change = {
            'parent_id': 'parent-open',
            'price': 1497.5,
        }
        try:
            self.commands.modify_held(held_change)
        except RefusedRequestError as refusal:
            print(f'Held change: {refusal.status} {refusal.body["error"]}')
        finished_parent = {
            'command': 'cancel_parent',
            'body': {
                'parent_id': 'parent-done',
            },
        }
        self.refused('Finished parent', finished_parent)

        stuck_arguments = {
            'parent_id': 'parent-stuck',
        }
        body, status = self.commands.cancel_parent(stuck_arguments)
        print(f'Cancel parent with a refused leg answered {status}: state {body["state"]}')
        for leg in body['cancelled_legs']:
            print(f'  {leg["broker"]} {leg["order_id"]}: {leg["outcome"]}, {leg["status_message"]}')

        self.commands.halt('parent-open')
        print(f'parent-open after halting: {self.parent_store.documents["parent-open"]["state"]}')
        self.commands.halt('parent-missing')
        print(f'Halting a missing parent changed nothing: {"parent-missing" not in self.parent_store.documents}')
        print(f'Sent to the broker: {self.placement.sent}')

        runner = self.commands.runner_for('parent-filled')
        print(f'runner_for gives a {type(runner).__name__} holding {runner.parent.parent_order_id}')
        leg_arguments = {
            'broker': 'zerodha',
            'order_id': '250930000201',
        }
        try:
            self.commands.leg_to_change(runner, leg_arguments)
        except RefusedRequestError as refusal:
            print(f'leg_to_change refuses: {refusal.body}')
        leg = runner.parent.legs[0]
        body, status = self.commands.answered(runner, leg, 'unknown', 'the broker did not answer in time', None)
        print(f'An unknown outcome is answered {status}: {body["status_message"]}')
        print(f'Prices read as decimals: {self.commands.decimal_or_none(1497.55)} and {self.commands.decimal_or_none(None)}')


if __name__ == '__main__':
    RefusalsAndHaltingExample().run()
