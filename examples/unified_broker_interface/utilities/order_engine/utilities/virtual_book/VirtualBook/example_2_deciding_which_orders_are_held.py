"""Shows how the synthetic limit order book decides which open orders to follow, and when it starts an estimate again.

Every two seconds a `VirtualBook` reads the engine's open parents and keeps an estimate only for an order still held: a plan's order waiting on a `limit_marketable` trigger, whose trigger wrote the terms it is held at. `held_documents` turns each such order into a record of its own, keyed by the parent id and the order's path. This program gives it five open plans and one stored estimate for a plan that has since closed, then asks each question `refresh` asks, one at a time, before calling `refresh` itself.

The five plans are a plain held buy, one whose order has already been sent, one waiting on a price rather than held, one whose price was changed through `PUT /api/orders/modify` after the book had started following it, and one with no side, which cannot be followed. Redis is a small stand-in holding the stored estimates, the parent cache is a dictionary, and the logger prints its warnings so they appear in the output.

Notice that the stored estimate for the changed order is thrown away because its price no longer matches, that the closed plan's estimate is removed from Redis, and that only the two held orders end up followed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/virtual_book/VirtualBook/example_2_deciding_which_orders_are_held.py
"""

import json

from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
    VirtualBook,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_queue import (
    VirtualQueue,
)


class StandInRedis:
    """The hash commands the book uses when refreshing, over dictionaries.

    Attributes:
        hashes (dict): Each hash's fields, by key.
    """

    def __init__(self, hashes):
        """Builds the stand-in with some hashes already filled.

        Args:
            hashes (dict): Each hash's fields, by key.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = hashes

    def hget(self, key, field):
        """Reads one hash field.

        Args:
            key (str): The hash.
            field (str): The field.

        Returns:
            str | None: The value.
        """
        return self.hashes.get(key, {}).get(field)

    def hkeys(self, key):
        """Lists one hash's fields.

        Args:
            key (str): The hash.

        Returns:
            list: The fields.
        """
        return list(self.hashes.get(key, {}))

    def hdel(self, key, *fields):
        """Removes hash fields.

        Args:
            key (str): The hash.
            *fields (str): The fields.

        Returns:
            int: How many were removed.
        """
        removed = 0
        for field in fields:
            if self.hashes.get(key, {}).pop(field, None) is not None:
                removed = removed + 1
        return removed


class StandInParentStore:
    """The engine's parent cache, as a dictionary of open parents.

    Attributes:
        documents (dict): Each open parent's document, by id.
    """

    def __init__(self, documents):
        """Builds the stand-in.

        Args:
            documents (dict): Each open parent's document, by id.

        Returns:
            None: This method returns nothing.
        """
        self.documents = documents

    def open_parent_ids(self):
        """The ids of every open parent.

        Returns:
            list: The ids, sorted.
        """
        return sorted(self.documents)

    def parent(self, parent_order_id):
        """One parent's document.

        Args:
            parent_order_id (str): The id.

        Returns:
            dict | None: The document.
        """
        return self.documents.get(parent_order_id)


class PrintingLogger:
    """A logger that prints each message, so the book's warnings are part of the output."""

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'WARNING {message}')


class DecidingWhichOrdersAreHeldExample:
    """Asks the book about five open plans and then lets it refresh.

    Attributes:
        documents (dict): The open parents, by id.
        cache (StandInRedis): The stand-in Redis, holding two stored estimates.
        book (VirtualBook): The book being shown.
    """

    def __init__(self):
        """Builds the parents, the stored estimates and the book.

        Returns:
            None: This method returns nothing.
        """
        self.documents = {
            'held': self.parent('held', 'BUY', '98', 500),
            'fired': self.parent('fired', 'BUY', '98', 500, part_state='working'),
            'priced': self.parent('priced', 'BUY', '98', 500, held=False),
            'changed': self.parent('changed', 'SELL', '100.5', 300),
            'no_side': self.parent('no_side', None, '98', 500),
        }
        old_changed = VirtualQueue('changed/root', 'NSE:INFY', 'SELL', 101, 300)
        old_changed.ahead = 2500
        closed = VirtualQueue('closed/root', 'NSE:INFY', 'BUY', 97, 100)
        self.cache = StandInRedis(
            {
                ESTIMATES_KEY: {
                    'changed/root': json.dumps(old_changed.document()),
                    'closed/root': json.dumps(closed.document()),
                },
            },
        )
        self.book = VirtualBook(
            self.cache,
            StandInParentStore(self.documents),
            PrintingLogger(),
        )

    def parent(self, parent_order_id, side, price, quantity, part_state='waiting', held=True):
        """Builds one open plan of one order as the engine's cache holds it.

        Args:
            parent_order_id (str): The parent's id.
            side (str | None): BUY, SELL or None.
            price (str): The price the order is held at.
            quantity (int): The quantity.
            part_state (str): The order's state: `waiting` while held, `working` once sent.
            held (bool): Whether the order's trigger wrote held terms, which an order waiting on a price does not.

        Returns:
            dict: The document.
        """
        trigger_memory = {}
        if held:
            trigger_memory['held'] = {
                'instrument_id': 'NSE:INFY',
                'transaction_type': side,
                'price': price,
                'quantity': quantity,
            }
        return {
            'parent_order_id': parent_order_id,
            'synthetic_type': 'plan',
            'state': 'received',
            'instrument_id': 'NSE:INFY',
            'body': {
                'transaction_type': side,
                'order_type': 'LIMIT',
                'price': price,
                'quantity': quantity,
            },
            'parameters': {
                'type': 'plan',
                'parts': {
                    'root': {
                        'state': part_state,
                        'memory': {
                            'trigger': trigger_memory,
                        },
                    },
                },
            },
            'legs': [],
        }

    def run(self):
        """Prints each question's answer for every parent, then refreshes.

        Returns:
            None: This method returns nothing.
        """
        for parent_order_id, document in self.documents.items():
            records = self.book.held_documents(document)
            shown = []
            for record in records:
                price, quantity = self.book.held_terms(record)
                shown.append(f'{record["parent_order_id"]} at ({price}, {quantity})')
            print(f'{parent_order_id}: followed as {shown}')
        changed = self.book.held_documents(self.documents['changed'])[0]
        stored = self.book.stored_estimate('changed/root')
        print(f'Stored estimate for changed/root: price {stored.price}, ahead {stored.ahead}, rebased on next quote {stored.needs_baseline}')
        print(f'Its terms have changed since: {self.book.has_new_terms(stored, changed)}')
        fresh = self.book.new_estimate(changed)
        print(f'A fresh estimate: {fresh.side} {fresh.quantity} at {fresh.price}, ahead {fresh.ahead}')
        print(f'No side gives: {self.book.new_estimate(self.book.held_documents(self.documents["no_side"])[0])}')
        print(f'Nothing stored for held/root: {self.book.stored_estimate("held/root")}')
        self.book.refresh()
        print(f'Followed after refresh: {sorted(self.book.estimates)}')
        print(f'Waiting to be written: {sorted(self.book.changed)}')
        print(f'Stored estimates left in Redis: {self.cache.hkeys(ESTIMATES_KEY)}')
        self.documents.pop('changed')
        self.book.drop_finished(self.book.parent_store.open_parent_ids())
        print(f'After the changed order closes: {self.cache.hkeys(ESTIMATES_KEY)}')


if __name__ == '__main__':
    DecidingWhichOrdersAreHeldExample().run()
