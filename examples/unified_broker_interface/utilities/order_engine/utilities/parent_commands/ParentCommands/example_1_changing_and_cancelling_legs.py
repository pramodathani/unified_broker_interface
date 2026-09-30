"""Runs three changes a caller asks for on parents the engine owns: move a leg's price, cancel a leg, and cancel a whole parent.

When a caller sends `PUT /api/orders/modify` or `DELETE /api/orders/cancel` for an order the engine placed, the route does not call the broker itself. It hands the engine an intent carrying a command, and the worker that owns the parent runs it through `ParentCommands`. The commands rebuild the parent's own order type from its stored record with `runner_for`, find the leg with `leg_to_change`, and let the order type send the change and record it, so the type carries on from the caller's values.

This program runs the three commands on two `simple` parents that each have one limit order resting at Zerodha. The first parent's buy order is moved from 1498.00 to 1499.50 and then cancelled. The second parent is cancelled as a whole, through `run` with an intent exactly as the engine hands it over, which cancels its resting leg and ends the parent as `cancelled`. The answers come back as a body and an HTTP status, exactly as the route will answer the caller.

A stand-in placement accepts every change and cancel without calling a broker and records what it was asked to send. A stand-in parent store keeps the parents' records in a dictionary, and a stand-in event log keeps the events so the program can print them. The program needs no broker, no data store and no network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_commands/ParentCommands/example_1_changing_and_cancelling_legs.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.parent_commands import (
    ParentCommands,
)

INFY = '11111111-1111-5111-8111-000000000001'


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


class AcceptingPlacement:
    """A stand-in for the engine's placement that accepts every change and cancel without calling a broker.

    Attributes:
        sent (list): What was sent, one line per request.
    """

    def __init__(self):
        """Builds the placement with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.sent = []

    def accepted(self, broker_order_id):
        """Builds an accepted answer for one order.

        Args:
            broker_order_id (str): The broker's order id.

        Returns:
            BrokerAnswerStandIn: The answer.
        """
        response_body = {
            'status': 'success',
            'data': {
                'order_id': broker_order_id,
            },
        }
        return BrokerAnswerStandIn('accepted', None, response_body)

    def modify_leg(self, broker_name, broker_order_id, quantity=None, price=None, trigger_price=None):
        """Accepts a change to one order.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's order id.
            quantity (int | None): The new quantity, or None to keep it.
            price (decimal.Decimal | None): The new price, or None to keep it.
            trigger_price (decimal.Decimal | None): The new trigger price, or None to keep it.

        Returns:
            BrokerAnswerStandIn: An accepted answer.
        """
        self.sent.append(f'modify {broker_name} {broker_order_id} quantity={quantity} price={price} trigger_price={trigger_price}')
        return self.accepted(broker_order_id)

    def cancel(self, broker_name, broker_order_id):
        """Accepts a cancel of one order.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's order id.

        Returns:
            BrokerAnswerStandIn: An accepted answer.
        """
        self.sent.append(f'cancel {broker_name} {broker_order_id}')
        return self.accepted(broker_order_id)


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


class ChangingAndCancellingLegsExample:
    """Runs a change, a leg cancel and a parent cancel, and prints each answer.

    Attributes:
        placement (AcceptingPlacement): The stand-in placement.
        parent_store (DictionaryParentStore): The stand-in parent store.
        event_log (ListEventLog): The stand-in event log.
        commands (ParentCommands): The commands being shown.
    """

    def __init__(self):
        """Builds the commands over two stored parents.

        Returns:
            None: This method returns nothing.
        """
        documents = {
            'parent-1': self.document('parent-1', '250930000101'),
            'parent-2': self.document('parent-2', '250930000102'),
        }
        self.placement = AcceptingPlacement()
        self.parent_store = DictionaryParentStore(documents)
        self.event_log = ListEventLog()
        self.commands = ParentCommands(
            self.placement,
            self.event_log,
            self.parent_store,
            logging.getLogger('example'),
            None,
        )

    def document(self, parent_order_id, broker_order_id):
        """Builds the record of a `simple` parent with one buy limit order resting at Zerodha.

        Args:
            parent_order_id (str): The parent's id.
            broker_order_id (str): Zerodha's id for the resting order.

        Returns:
            dict: The record.
        """
        return {
            'parent_order_id': parent_order_id,
            'synthetic_type': 'simple',
            'state': 'working',
            'instrument_id': INFY,
            'body': {},
            'parameters': {},
            'legs': [
                {
                    'leg_id': f'{parent_order_id}-1',
                    'role': 'entry',
                    'state': 'acknowledged',
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

    def run(self):
        """Runs the three commands and prints the answers, what was sent and what was recorded.

        Returns:
            None: This method returns nothing.
        """
        modify_arguments = {
            'parent_id': 'parent-1',
            'broker': 'zerodha',
            'order_id': '250930000101',
            'price': '1499.50',
        }
        body, status = self.commands.modify_leg(modify_arguments)
        print(f'Modify answered {status}: {body["outcome"]} for {body["broker"]} {body["order_id"]} of {body["parent_id"]}')
        stored_price = self.parent_store.documents['parent-1']['legs'][0]['price']
        print(f'The stored leg now has the price {stored_price}')
        cancel_arguments = {
            'parent_id': 'parent-1',
            'broker': 'zerodha',
            'order_id': '250930000101',
        }
        body, status = self.commands.cancel_leg(cancel_arguments)
        print(f'Cancel answered {status}: {body["outcome"]}, broker said {body["broker_response"]}')
        cancel_parent_intent = {
            'command': 'cancel_parent',
            'body': {
                'parent_id': 'parent-2',
            },
        }
        body, status = self.commands.run(cancel_parent_intent)
        print(f'Cancel parent answered {status}: state {body["state"]}, {len(body["cancelled_legs"])} leg cancelled')
        print('Sent to the broker:')
        for line in self.placement.sent:
            print(f'  {line}')
        print('Recorded:')
        for event in self.event_log.events:
            print(f'  {event["parent_order_id"]} {event["event"]} {event.get("outcome") or event.get("parent_state")}')


if __name__ == '__main__':
    ChangingAndCancellingLegsExample().run()
