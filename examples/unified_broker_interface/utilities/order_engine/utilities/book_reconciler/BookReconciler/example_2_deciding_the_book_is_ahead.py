"""Shows when the reconciler runs, and how it decides that a polled book is ahead of the engine.

`due` answers whether enough time has passed since the last pass; an interval of 0 turns reconciliation off. The program passes monotonic times measured from the reconciler's own `checked_at`, so the answers are the same on every run.

`is_ahead` takes a change only when it moves the leg forward: a finished status, or more filled than the leg records. A poll is older than a socket message, so an `OPEN` entry beside a leg that already filled is the book being behind. `order_in_entry` pulls the normalized order out of a stored book entry and treats anything unreadable as no entry, and `book_entries` reads every leg's entry in one pipeline. A small in-memory stand-in replaces the Redis client; the parent store is not used by these calls, so it is passed as None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/book_reconciler/BookReconciler/example_2_deciding_the_book_is_ahead.py
"""

import json

from unified_broker_interface.utilities.order_engine.utilities.book_reconciler import (
    BookReconciler,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


class MemoryRedis:
    """A stand-in for the Redis client that keeps hashes and sets in dictionaries.

    Attributes:
        hashes (dict): Each hash key's fields and values.
        sets (dict): Each set key's members.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.sets = {}

    def pipeline(self, transaction=True):
        """Starts a pipeline that runs its commands on this stand-in when executed.

        Args:
            transaction (bool): Whether the real client would wrap the commands in MULTI; ignored here.

        Returns:
            MemoryPipeline: The pipeline.
        """
        return MemoryPipeline(self)

    def hget(self, key, field):
        """Reads one field of a hash.

        Args:
            key (str): The hash's key.
            field (str): The field.

        Returns:
            str | None: The value, or None when it is missing.
        """
        return self.hashes.get(key, {}).get(field)

    def hmget(self, key, fields):
        """Reads several fields of a hash.

        Args:
            key (str): The hash's key.
            fields (list): The fields.

        Returns:
            list: One value (str) or None per field.
        """
        values = []
        for field in fields:
            values.append(self.hget(key, field))
        return values

    def smembers(self, key):
        """Reads every member of a set.

        Args:
            key (str): The set's key.

        Returns:
            set: The members.
        """
        return set(self.sets.get(key, set()))


class MemoryPipeline:
    """A stand-in for a Redis pipeline that queues commands and runs them on `execute`.

    Attributes:
        cache (MemoryRedis): The stand-in the commands run on.
        commands (list): The queued commands, as tuples starting with the command's name.
    """

    def __init__(self, cache):
        """Builds an empty pipeline.

        Args:
            cache (MemoryRedis): The stand-in the commands run on.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.commands = []

    def hset(self, key, field, value):
        """Queues setting one field of a hash.

        Args:
            key (str): The hash's key.
            field (str): The field.
            value (str): The value.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('hset', key, field, value))

    def hget(self, key, field):
        """Queues reading one field of a hash.

        Args:
            key (str): The hash's key.
            field (str): The field.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('hget', key, field))

    def sadd(self, key, member):
        """Queues adding a member to a set.

        Args:
            key (str): The set's key.
            member (str): The member.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('sadd', key, member))

    def srem(self, key, member):
        """Queues removing a member from a set.

        Args:
            key (str): The set's key.
            member (str): The member.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('srem', key, member))

    def expireat(self, key, moment):
        """Queues setting when a key expires, which this stand-in ignores.

        Args:
            key (str): The key.
            moment (int): The Unix time it expires at.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('expireat', key, moment))

    def execute(self):
        """Runs every queued command in order.

        Returns:
            list: One reply per command: the value for `hget`, None for the rest.
        """
        replies = []
        for command in self.commands:
            name = command[0]
            key = command[1]
            reply = None
            if name == 'hset':
                self.cache.hashes.setdefault(key, {})[command[2]] = command[3]
            elif name == 'hget':
                reply = self.cache.hget(key, command[2])
            elif name == 'sadd':
                self.cache.sets.setdefault(key, set()).add(command[2])
            elif name == 'srem':
                self.cache.sets.setdefault(key, set()).discard(command[2])
            replies.append(reply)
        return replies


class DecidingTheBookIsAheadExample:
    """Prints `due`, `is_ahead`, `order_in_entry` and `book_entries` answers.

    Attributes:
        cache (MemoryRedis): The stand-in Redis client.
        reconciler (BookReconciler): The reconciler being shown, checking every five seconds.
        switched_off (BookReconciler): A reconciler whose interval is 0.
        leg (OrderLeg): A leg the engine knows has filled 4 of 10.
    """

    def __init__(self):
        """Builds the reconcilers and the leg.

        Returns:
            None: This method returns nothing.
        """
        self.cache = MemoryRedis()
        self.reconciler = BookReconciler(self.cache, None, 5.0)
        self.switched_off = BookReconciler(self.cache, None, 0)
        self.leg = OrderLeg('parent-a:1', 'entry')
        self.leg.state = 'partially_filled'
        self.leg.broker = 'kotak'
        self.leg.broker_order_id = '250930000000777'
        self.leg.quantity = 10
        self.leg.filled_quantity = 4

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        start = self.reconciler.checked_at
        print(f'Due after 4.9 seconds: {self.reconciler.due(now=start + 4.9)}')
        print(f'Due after 5 seconds: {self.reconciler.due(now=start + 5.0)}')
        print(f'Due when switched off, an hour later: {self.switched_off.due(now=start + 3600)}')
        book_orders = [
            (
                'OPEN, 4 filled',
                {
                    'status': 'OPEN',
                    'filled_quantity': 4,
                },
            ),
            (
                'OPEN, 7 filled',
                {
                    'status': 'OPEN',
                    'filled_quantity': 7,
                },
            ),
            (
                'OPEN, 0 filled',
                {
                    'status': 'OPEN',
                    'filled_quantity': 0,
                },
            ),
            (
                'rejected',
                {
                    'status': 'rejected',
                    'filled_quantity': None,
                },
            ),
            (
                'no fill reported',
                {
                    'status': 'OPEN',
                    'filled_quantity': None,
                },
            ),
        ]
        for label, order in book_orders:
            print(f'Book shows {label}: ahead={self.reconciler.is_ahead(self.leg, order)}')
        readable_entry = {
            'order': {
                'status': 'OPEN',
            },
        }
        entry_without_order = {
            'raw': 'no normalized order',
        }
        stored_entries = [
            json.dumps(readable_entry),
            json.dumps(entry_without_order),
            '[1, 2]',
            'not json',
            None,
        ]
        for stored in stored_entries:
            print(f'order_in_entry({stored!r}) = {self.reconciler.order_in_entry(stored)}')
        completed_entry = {
            'order': {
                'status': 'COMPLETE',
                'filled_quantity': 10,
            },
        }
        self.cache.hashes['kotak:orders:orders'] = {
            '250930000000777': json.dumps(completed_entry),
        }
        other_leg = OrderLeg('parent-b:1', 'entry')
        other_leg.broker = 'kotak'
        other_leg.broker_order_id = '250930000000999'
        entries = self.reconciler.book_entries([
            (
                'parent-a',
                self.leg,
            ),
            (
                'parent-b',
                other_leg,
            ),
        ])
        print(f'Book entries for two legs: {entries}')


if __name__ == '__main__':
    DecidingTheBookIsAheadExample().run()
