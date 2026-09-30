"""Shows the document an intent writes to the engine's stream, for an order in a list and for a command.

`document()` is what the API worker hands to the engine. An order that arrived on its own gets a reply key of its own, but every order of one list shares the reply key the route chose, and carries its `request_index` so the answers can be put back in order. A command, such as cancelling one leg of a parent the engine owns, carries `command` instead of a synthetic type.

The intent id, the creation time and the API worker's host and process id differ on every run, so the program prints only whether each is present, and prints the waiting time as the deadline minus the creation time. Everything else is printed exactly.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_intent/OrderIntent/example_2_documents_for_the_stream.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_intent import (
    OrderIntent,
)


class DocumentsForTheStreamExample:
    """Builds an order from a list and a command, and prints their stream documents.

    Attributes:
        shared_reply_key (str): The reply key every order of the pretend list shares.
    """

    def __init__(self):
        """Chooses the shared reply key.

        Returns:
            None: This method returns nothing.
        """
        self.shared_reply_key = 'unified:orders:intents:result:list-0001'

    def show(self, label, intent):
        """Prints one intent's document with the run-dependent fields masked.

        Args:
            label (str): What the intent is.
            intent (OrderIntent): The intent to print.

        Returns:
            None: This method returns nothing.
        """
        document = intent.document()
        print(label)
        for name in sorted(document):
            value = document[name]
            if name in ('intent_id', 'created_at', 'api_worker'):
                value = '<differs on every run>'
            if name == 'deadline_at':
                value = f'created_at + {round(document["deadline_at"] - document["created_at"], 3)} seconds'
            if name == 'reply_key' and value.endswith(document['intent_id']):
                value = 'unified:orders:intents:result:<intent_id>'
            print(f'  {name}: {value}')

    def run(self):
        """Prints the documents of a listed order, a lone order and a command.

        Returns:
            None: This method returns nothing.
        """
        listed_order = OrderIntent(
            {
                'transaction_type': 'BUY',
                'order_type': 'MARKET',
                'quantity': 75,
            },
            'NFO:NIFTY25OCT25000CE',
            15,
            request_index=2,
            reply_key=self.shared_reply_key,
        )
        self.show('Third order of a list:', listed_order)
        lone_order = OrderIntent(None, 'NSE:SBIN', 5)
        self.show('An order with no body:', lone_order)
        command = OrderIntent(
            {
                'parent_id': 'p-7f3a',
                'leg_id': 'p-7f3a:2',
            },
            'NSE:SBIN',
            5,
            command='cancel_leg',
        )
        self.show('A cancel_leg command:', command)


if __name__ == '__main__':
    DocumentsForTheStreamExample().run()
