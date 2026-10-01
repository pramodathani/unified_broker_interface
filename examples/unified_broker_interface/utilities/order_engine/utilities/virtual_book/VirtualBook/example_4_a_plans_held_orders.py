"""Shows the synthetic limit order book following the held orders of a plan, each under its own key.

A plan can hold several orders at once, so `VirtualBook.held_documents` turns each order still waiting on a `limit_marketable` trigger into a record of its own, built from the terms the trigger wrote into the order's memory, and keyed by `VirtualBook.part_key`: the parent id and the order's path. This program gives the book a plan with two held orders, one order that has already been sent and one waiting on a price, and a plain `virtual_limit` parent beside it. Redis is a small stand-in, and the parent cache is a dictionary.

Notice that the sent order and the one waiting on a price are not followed, and that when the plan closes both of its estimates are removed, because each key starts with the plan's parent id.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/virtual_book/VirtualBook/example_4_a_plans_held_orders.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
    QUOTES_STREAM_KEY,
    VirtualBook,
)
class StandInPipeline:
    """A Redis pipeline that writes into the stand-in's hashes when executed.

    Attributes:
        cache (StandInRedis): The stand-in written to.
        writes (list): The queued (key, field, value) writes.
    """

    def __init__(self, cache):
        """Builds an empty pipeline.

        Args:
            cache (StandInRedis): The stand-in written to.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.writes = []

    def hset(self, key, field, value):
        """Queues one hash write.

        Args:
            key (str): The hash.
            field (str): The field.
            value (str): The value.

        Returns:
            None: This method returns nothing.
        """
        self.writes.append((key, field, value))

    def execute(self):
        """Applies every queued write.

        Returns:
            list: One True per write.
        """
        results = []
        for key, field, value in self.writes:
            self.cache.hashes.setdefault(key, {})[field] = value
            results.append(True)
        return results


class StandInRedis:
    """The few Redis commands the book uses, over dictionaries and a list of stream entries.

    Attributes:
        hashes (dict): Each hash's fields, by key.
        stream (list): The (entry id, fields) pairs on the quote stream, oldest first.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.stream = []

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

    def pipeline(self, transaction=True):
        """Starts a pipeline.

        Args:
            transaction (bool): Ignored.

        Returns:
            StandInPipeline: The pipeline.
        """
        return StandInPipeline(self)

    def xread(self, streams, count=None, block=None):
        """Returns the stream entries after the id asked for, treating `$` as the start of the list.

        Args:
            streams (dict): The stream key and the id to read after.
            count (int | None): Ignored.
            block (int | None): Ignored.

        Returns:
            list: One (stream key, entries) pair, or an empty list.
        """
        after = streams[QUOTES_STREAM_KEY]
        entries = []
        for entry_id, fields in self.stream:
            if after == '$' or entry_id > after:
                entries.append((entry_id, fields))
        if not entries:
            return []
        return [
            (QUOTES_STREAM_KEY, entries),
        ]


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


class PlansHeldOrdersExample:
    """Asks the book which of a plan's orders it follows, then lets it refresh and write.

    Attributes:
        documents (dict): The open parents, by id.
        cache (StandInRedis): The stand-in Redis.
        book (VirtualBook): The book being shown.
    """

    def __init__(self):
        """Builds the parents and the book.

        Returns:
            None: This method returns nothing.
        """
        self.documents = {
            'plan': self.plan(),
            'single': {
                'parent_order_id': 'single',
                'synthetic_type': 'virtual_limit',
                'state': 'received',
                'instrument_id': 'NSE:INFY',
                'body': {
                    'transaction_type': 'BUY',
                    'order_type': 'LIMIT',
                    'price': 1500,
                    'quantity': 10,
                },
                'parameters': {
                    'type': 'virtual_limit',
                },
                'legs': [],
            },
        }
        self.cache = StandInRedis()
        self.book = VirtualBook(
            self.cache,
            StandInParentStore(self.documents),
            logging.getLogger('example'),
        )

    def held(self, instrument_id, side, price, quantity):
        """The terms a `limit_marketable` trigger writes into an order's memory.

        Args:
            instrument_id (str): The order's instrument.
            side (str): BUY or SELL.
            price (str): The limit price.
            quantity (int): The quantity.

        Returns:
            dict: The order's memory.
        """
        return {
            'trigger': {
                'held': {
                    'instrument_id': instrument_id,
                    'transaction_type': side,
                    'price': price,
                    'quantity': quantity,
                },
            },
        }

    def plan(self):
        """A plan of four orders as the engine's cache holds it.

        Returns:
            dict: The document.
        """
        return {
            'parent_order_id': 'plan',
            'synthetic_type': 'plan',
            'state': 'received',
            'instrument_id': 'NSE:INFY',
            'body': {},
            'parameters': {
                'parts': {
                    'root.together.0': {
                        'state': 'waiting',
                        'memory': self.held('NSE:INFY', 'BUY', '1498.5', 20),
                    },
                    'root.together.1': {
                        'state': 'waiting',
                        'memory': self.held('NSE:TCS', 'SELL', '3610', 5),
                    },
                    'root.together.2': {
                        'state': 'working',
                        'memory': self.held('NSE:INFY', 'BUY', '1497', 20),
                    },
                    'root.together.3': {
                        'state': 'waiting',
                        'memory': {
                            'trigger': {},
                        },
                    },
                },
            },
            'legs': [],
        }

    def run(self):
        """Prints what the book follows, then what it writes and what it removes.

        Returns:
            None: This method returns nothing.
        """
        print(f'The key for root.together.1: {VirtualBook.part_key("plan", "root.together.1")}')
        for parent_order_id, document in self.documents.items():
            print(f'{parent_order_id} holds:')
            for held in self.book.held_documents(document):
                body = held['body']
                print(f'  {held["parent_order_id"]}: {body["transaction_type"]} {body["quantity"]} of {held["instrument_id"]} at {body["price"]}')
        self.book.refresh()
        print(f'Followed after refresh: {sorted(self.book.estimates)}')
        print(f'By instrument: {self.book.by_instrument}')
        self.book.write_changed()
        print(f'Written to Redis: {sorted(self.cache.hkeys(ESTIMATES_KEY))}')
        self.documents.pop('plan')
        self.book.refresh()
        print(f'After the plan closes: {sorted(self.cache.hkeys(ESTIMATES_KEY))}')


if __name__ == '__main__':
    PlansHeldOrdersExample().run()
