"""Shows how the synthetic limit order book decides which open orders to follow, and when it starts an estimate again.

Every two seconds a `VirtualBook` reads the engine's open parents and keeps an estimate only for a `virtual_limit` order that is still held: one whose trigger has not fired and which has no leg other than a backstop. This program gives it five open parents and one stored estimate for a parent that has since closed, then asks each question `refresh` asks, one at a time, before calling `refresh` itself.

The five parents are a plain held buy, one that has already sent its entry leg, one of a different synthetic type, one whose price was changed through `PUT /api/orders/modify` after the book had started following it, and one with no side, which cannot be followed. Redis is a small stand-in holding the stored estimates, the parent cache is a dictionary, and the logger prints its warnings so they appear in the output.

Notice that the stored estimate for the changed order is thrown away because its price no longer matches, that the closed parent's estimate is removed from Redis, and that only the two held orders end up followed.

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
    """Asks the book about five open parents and then lets it refresh.

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
        fired = self.parent('fired', 'virtual_limit', 'BUY', 98, 500)
        fired['legs'] = [
            {
                'role': 'entry',
            },
        ]
        changed = self.parent('changed', 'virtual_limit', 'SELL', 101, 300)
        changed['parameters']['held_price'] = '100.5'
        self.documents = {
            'held': self.parent('held', 'virtual_limit', 'BUY', 98, 500),
            'fired': fired,
            'touched': self.parent('touched', 'limit_if_touched', 'BUY', 98, 500),
            'changed': changed,
            'no_side': self.parent('no_side', 'virtual_limit', None, 98, 500),
        }
        old_changed = VirtualQueue('changed', 'NSE:INFY', 'SELL', 101, 300)
        old_changed.ahead = 2500
        closed = VirtualQueue('closed', 'NSE:INFY', 'BUY', 97, 100)
        self.cache = StandInRedis(
            {
                ESTIMATES_KEY: {
                    'changed': json.dumps(old_changed.document()),
                    'closed': json.dumps(closed.document()),
                },
            },
        )
        self.book = VirtualBook(
            self.cache,
            StandInParentStore(self.documents),
            PrintingLogger(),
        )

    def parent(self, parent_order_id, synthetic_type, side, price, quantity):
        """Builds one open parent as the engine's cache holds it.

        Args:
            parent_order_id (str): The parent's id.
            synthetic_type (str): The synthetic order type.
            side (str | None): BUY, SELL or None.
            price (int): The limit price.
            quantity (int): The quantity.

        Returns:
            dict: The document.
        """
        return {
            'parent_order_id': parent_order_id,
            'synthetic_type': synthetic_type,
            'state': 'received',
            'instrument_id': 'NSE:INFY',
            'body': {
                'transaction_type': side,
                'order_type': 'LIMIT',
                'price': price,
                'quantity': quantity,
            },
            'parameters': {
                'type': synthetic_type,
            },
            'legs': [],
        }

    def run(self):
        """Prints each question's answer for every parent, then refreshes.

        Returns:
            None: This method returns nothing.
        """
        for parent_order_id, document in self.documents.items():
            price, quantity = self.book.held_terms(document)
            print(f'{parent_order_id}: held={self.book.is_held(document)} terms=({price}, {quantity})')
        stored = self.book.stored_estimate('changed')
        print(f'Stored estimate for changed: price {stored.price}, ahead {stored.ahead}, rebased on next quote {stored.needs_baseline}')
        print(f'Its terms have changed since: {self.book.has_new_terms(stored, self.documents["changed"])}')
        fresh = self.book.new_estimate(self.documents['changed'])
        print(f'A fresh estimate: {fresh.side} {fresh.quantity} at {fresh.price}, ahead {fresh.ahead}')
        print(f'No side gives: {self.book.new_estimate(self.documents["no_side"])}')
        print(f'Nothing stored for held: {self.book.stored_estimate("held")}')
        self.book.refresh()
        print(f'Followed after refresh: {sorted(self.book.estimates)}')
        print(f'Waiting to be written: {sorted(self.book.changed)}')
        print(f'Stored estimates left in Redis: {self.cache.hkeys(ESTIMATES_KEY)}')
        self.documents.pop('changed')
        self.book.drop_finished(self.book.parent_store.open_parent_ids())
        print(f'After the changed order closes: {self.cache.hkeys(ESTIMATES_KEY)}')


if __name__ == '__main__':
    DecidingWhichOrdersAreHeldExample().run()
