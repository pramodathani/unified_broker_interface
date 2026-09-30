"""Shows when the cache expires and how recovery replaces it wholesale, leaving no ghost parents behind.

Every write sets the four keys to expire at the next 06:00 IST, the boundary no order lives across. `reset_epochs` computes that boundary and the one before it; the program pins the moment it reckons from, once before 06:00 and once after, so the answer is the same on every run.

Recovery rebuilds parents from the event log and hands them to `rebuild`, which deletes the four keys before writing, so a parent the log no longer knows about disappears from the open set. The program saves a ghost parent first, rebuilds with two other parents, and shows the ghost gone. It also stores an unreadable record by hand to show that `parent` and `parents` skip it rather than fail.

A small in-memory stand-in replaces the Redis client, so no Redis server is needed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_store/ParentStore/example_2_expiry_and_rebuilding.py
"""

import datetime
import zoneinfo

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    PARENTS_KEY,
    ParentStore,
)


class MemoryRedis:
    """A stand-in for the Redis client that keeps hashes and sets in dictionaries.

    Attributes:
        hashes (dict): Each hash key's fields and values.
        sets (dict): Each set key's members.
        expiries (dict): The Unix time each key was told to expire at.
        round_trips (int): How many pipelines were executed.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.sets = {}
        self.expiries = {}
        self.round_trips = 0

    def pipeline(self, transaction=True):
        """Starts a pipeline that applies its commands to this stand-in when executed.

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
    """A stand-in for a Redis pipeline that queues commands and applies them on `execute`.

    Attributes:
        cache (MemoryRedis): The stand-in the commands are applied to.
        commands (list): The queued commands, as (name, arguments) pairs.
    """

    def __init__(self, cache):
        """Builds an empty pipeline.

        Args:
            cache (MemoryRedis): The stand-in the commands are applied to.

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

    def delete(self, key):
        """Queues deleting a key.

        Args:
            key (str): The key.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('delete', key))

    def expireat(self, key, moment):
        """Queues setting when a key expires.

        Args:
            key (str): The key.
            moment (int): The Unix time it expires at.

        Returns:
            None: This method returns nothing.
        """
        self.commands.append(('expireat', key, moment))

    def execute(self):
        """Applies every queued command in order.

        Returns:
            list: An empty list, since no caller reads the replies.
        """
        self.cache.round_trips += 1
        for command in self.commands:
            name = command[0]
            key = command[1]
            if name == 'hset':
                self.cache.hashes.setdefault(key, {})[command[2]] = command[3]
            elif name == 'sadd':
                self.cache.sets.setdefault(key, set()).add(command[2])
            elif name == 'srem':
                self.cache.sets.setdefault(key, set()).discard(command[2])
            elif name == 'delete':
                self.cache.hashes.pop(key, None)
                self.cache.sets.pop(key, None)
            elif name == 'expireat':
                self.cache.expiries[key] = command[2]
        return []


class ExpiryAndRebuildingExample:
    """Prints the reset boundaries and rebuilds the cache over a ghost parent.

    Attributes:
        cache (MemoryRedis): The stand-in Redis client.
        store (ParentStore): The store being shown.
        india (zoneinfo.ZoneInfo): India's time zone.
    """

    def __init__(self):
        """Builds the store over an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.cache = MemoryRedis()
        self.store = ParentStore(self.cache)
        self.india = zoneinfo.ZoneInfo('Asia/Kolkata')

    def show_reset(self, now):
        """Prints the reset boundaries around one moment.

        Args:
            now (datetime.datetime): The moment to reckon from.

        Returns:
            None: This method returns nothing.
        """
        latest, next_reset = self.store.reset_epochs(now)
        latest_text = datetime.datetime.fromtimestamp(latest, self.india).isoformat()
        next_text = datetime.datetime.fromtimestamp(next_reset, self.india).isoformat()
        print(f'At {now.isoformat()}: latest reset {latest_text}, next reset {next_text}')

    def parent(self, parent_order_id, state):
        """Builds a parent with no legs.

        Args:
            parent_order_id (str): The parent's id.
            state (str): The parent's state.

        Returns:
            ParentOrder: The parent.
        """
        parent = ParentOrder(parent_order_id)
        parent.state = state
        return parent

    def run(self):
        """Prints the boundaries, then rebuilds the cache.

        Returns:
            None: This method returns nothing.
        """
        self.show_reset(datetime.datetime(2026, 9, 30, 5, 59, tzinfo=self.india))
        self.show_reset(datetime.datetime(2026, 9, 30, 9, 15, tzinfo=self.india))
        self.store.save(self.parent('ghost', 'working'))
        print(f'Open before rebuilding: {self.store.open_parent_ids()}')
        self.store.rebuild([
            self.parent('parent-c', 'protecting'),
            self.parent('parent-d', 'cancelled'),
        ])
        print(f'Open after rebuilding: {self.store.open_parent_ids()}')
        print(f'Ghost document after rebuilding: {self.store.parent("ghost")}')
        self.cache.hashes[PARENTS_KEY]['broken'] = '{not json'
        print(f'Unreadable record: {self.store.parent("broken")}')
        documents = self.store.parents([
            'broken',
            'parent-d',
        ])
        print(f'Read together, skipping the unreadable one: {len(documents)} document, state {documents[0]["state"]}')
        print(f'Nothing asked for: {self.store.parents([])}')


if __name__ == '__main__':
    ExpiryAndRebuildingExample().run()
