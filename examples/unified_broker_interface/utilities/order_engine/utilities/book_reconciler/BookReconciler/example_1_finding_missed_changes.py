"""Finds a fill and a cancellation that no order socket delivered, by reading the brokers' polled order books.

The engine normally hears about its orders from the order update stream, which only order websockets feed. A broker without a socket, or a dropped message, would leave a filled or cancelled leg looking live for ever. `BookReconciler.missed_updates` reads each open leg's entry in its broker's polled book (`<broker>:orders:orders`) and returns an order update for every leg the book is ahead of.

The program saves three open legs through a real `ParentStore`, then writes the polled books by hand: Zerodha shows its leg fully filled, Dhan shows its leg cancelled, and Fyers shows its leg still `OPEN` with nothing filled. A small in-memory stand-in replaces the Redis client. Notice that only the two legs the book is ahead of come back, each as the stream entry the follower expects, and that the counters record one pass and two changes found. The reconciler only reports; it changes nothing, so until the follower applies an update and saves the parent, the next pass reports the same change again, which the second pass shows.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/book_reconciler/BookReconciler/example_1_finding_missed_changes.py
"""

import json

from unified_broker_interface.utilities.order_engine.utilities.book_reconciler import (
    BookReconciler,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
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


class FindingMissedChangesExample:
    """Saves three open legs, writes the polled books, and prints what the reconciler finds.

    Attributes:
        cache (MemoryRedis): The stand-in Redis client.
        parent_store (ParentStore): The Redis copy of the parents.
        reconciler (BookReconciler): The reconciler being shown.
    """

    def __init__(self):
        """Builds the store and the reconciler, checking every five seconds.

        Returns:
            None: This method returns nothing.
        """
        self.cache = MemoryRedis()
        self.parent_store = ParentStore(self.cache)
        self.reconciler = BookReconciler(self.cache, self.parent_store, 5.0)

    def save_parent(self, parent_order_id, broker, broker_order_id):
        """Saves a working parent with one sent entry leg.

        Args:
            parent_order_id (str): The parent's id.
            broker (str): The broker the leg was sent to.
            broker_order_id (str): The broker's order id.

        Returns:
            None: This method returns nothing.
        """
        parent = ParentOrder(parent_order_id)
        parent.state = 'working'
        leg = OrderLeg(parent.next_leg_id(), 'entry')
        leg.state = 'sent'
        leg.broker = broker
        leg.broker_order_id = broker_order_id
        leg.quantity = 10
        parent.legs.append(leg)
        self.parent_store.save(parent)

    def write_book(self, broker, broker_order_id, status, filled_quantity):
        """Writes one order into a broker's polled book, as the REST poller would.

        Args:
            broker (str): The broker.
            broker_order_id (str): The broker's order id.
            status (str): The order's status on the shared vocabulary.
            filled_quantity (int): How much has filled.

        Returns:
            None: This method returns nothing.
        """
        entry = {
            'order': {
                'order_id': broker_order_id,
                'status': status,
                'quantity': 10,
                'filled_quantity': filled_quantity,
            },
        }
        self.cache.hashes.setdefault(f'{broker}:orders:orders', {})[broker_order_id] = json.dumps(entry)

    def run(self):
        """Runs one pass and prints the missed updates.

        Returns:
            None: This method returns nothing.
        """
        self.save_parent('parent-a', 'zerodha', '250930000123456')
        self.save_parent('parent-b', 'dhan', '1102509300004567')
        self.save_parent('parent-c', 'fyers', '52509300001234')
        self.write_book('zerodha', '250930000123456', 'COMPLETE', 10)
        self.write_book('dhan', '1102509300004567', 'CANCELLED', 0)
        self.write_book('fyers', '52509300001234', 'OPEN', 0)
        open_legs = []
        for parent_order_id, leg in self.reconciler.open_legs():
            open_legs.append(f'{parent_order_id}/{leg.broker}')
        print(f'Open legs: {open_legs}')
        for parent_order_id, broker, fields in self.reconciler.missed_updates():
            print(f'Missed for {parent_order_id} at {broker}: {fields}')
        print(f'Passes: {self.reconciler.passes}, changes found: {self.reconciler.found}')
        print(f'A second pass finds: {self.reconciler.missed_updates()}')


if __name__ == '__main__':
    FindingMissedChangesExample().run()
