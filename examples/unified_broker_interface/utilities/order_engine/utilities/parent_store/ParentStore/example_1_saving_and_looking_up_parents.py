"""Saves two parent orders to the Redis cache and looks them up the ways the engine does.

`ParentStore` keeps four Redis keys: every parent's document, the set of parents still open, a map from each broker order to its parent, and a map from each intent to its parent. `save` writes all four for one parent in one round trip, and the lookups read them back.

A small in-memory stand-in replaces the Redis client, so the program runs without a Redis server; it keeps hashes and sets in dictionaries and applies a pipeline's commands when it is executed. The program saves one working order and one completed order, then asks which parents are open, which parent owns a broker order, which parent an intent started, and reads the documents back. Notice that the completed parent is kept but left out of the open set, and that an unknown broker order maps to None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_store/ParentStore/example_1_saving_and_looking_up_parents.py
"""

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


class SavingAndLookingUpParentsExample:
    """Saves two parents and prints what each lookup returns.

    Attributes:
        cache (MemoryRedis): The stand-in Redis client.
        store (ParentStore): The store being shown.
    """

    def __init__(self):
        """Builds the store over an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.cache = MemoryRedis()
        self.store = ParentStore(self.cache)

    def parent_with_leg(self, parent_order_id, intent_id, state, broker, broker_order_id):
        """Builds a parent with one entry leg at a broker.

        Args:
            parent_order_id (str): The parent's id.
            intent_id (str): The intent that started it.
            state (str): The parent's state.
            broker (str): The broker the leg was sent to.
            broker_order_id (str): The broker's order id.

        Returns:
            ParentOrder: The parent.
        """
        parent = ParentOrder(parent_order_id)
        parent.intent_id = intent_id
        parent.state = state
        parent.instrument_id = 'NSE:INFY'
        leg = OrderLeg(parent.next_leg_id(), 'entry')
        leg.state = 'sent'
        leg.broker = broker
        leg.broker_order_id = broker_order_id
        parent.legs.append(leg)
        return parent

    def run(self):
        """Saves the parents and prints the lookups.

        Returns:
            None: This method returns nothing.
        """
        working = self.parent_with_leg('parent-a', 'intent-a', 'working', 'zerodha', '250930000123456')
        completed = self.parent_with_leg('parent-b', 'intent-b', 'completed', 'dhan', '1102509300004567')
        self.store.save(working)
        self.store.save(completed)
        print(f'Round trips: {self.cache.round_trips}')
        print(f'Open parents: {self.store.open_parent_ids()}')
        print(f'zerodha 250930000123456 belongs to: {self.store.parent_for_broker_order("zerodha", "250930000123456")}')
        print(f'zerodha 999 belongs to: {self.store.parent_for_broker_order("zerodha", "999")}')
        owners = self.store.parents_for_broker_orders([
            'dhan:1102509300004567',
            'zerodha:250930000123456',
            'fyers:1',
        ])
        print(f'Owners of three broker orders: {owners}')
        print(f'intent-b started: {self.store.parent_for_intent("intent-b")}')
        document = self.store.parent('parent-a')
        print(f'parent-a: state={document["state"]} legs={len(document["legs"])} instrument={document["instrument_id"]}')
        print(f'missing parent: {self.store.parent("parent-z")}')
        documents = self.store.parents([
            'parent-b',
            'parent-z',
            'parent-a',
        ])
        states = []
        for document in documents:
            states.append(f'{document["parent_order_id"]}={document["state"]}')
        print(f'Read together: {states}')
        print(f'Keys with an expiry: {sorted(self.cache.expiries)}')


if __name__ == '__main__':
    SavingAndLookingUpParentsExample().run()
