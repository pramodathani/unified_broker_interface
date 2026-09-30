"""Feeds the engine the brokers' order updates on its own thread and shows what it applies, what it holds and what it finds in the polled order books.

Besides intents, the engine reads `unified:order-updates`, the stream every broker's order socket feeds. `take_update` hands one entry to `apply_update`, which asks the follower whether the update belongs to one of the engine's legs, saves the changed parent, and acknowledges the entry either way. An update that fails to apply is logged and acknowledged too, because the broker's book is read again later.

An update can arrive before the engine has heard the broker's answer with the order id, and the follower holds it. After every read, `take_early_updates` asks for the held updates whose order is now known; without worker lanes it calls `replay_early_updates`, which applies them all. `apply_replayed_update` applies one such held update. `reconcile_books` asks the book reconciler for changes that the polled order books show and no socket delivered, and applies each with `apply_reconciled_update`. At 06:00 IST, `roll_day` rebuilds the parent caches.

The follower, the reconciler and the day roll are small stand-in classes defined here, so the program controls which updates are known, held or missed; the real ones read Redis and replay the order types' reactions. Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py`, and the parent store is the real one over it, so the printed states are what the engine saved. No broker is contacted and no order is placed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_runner/OrderEngine/example_5_following_broker_order_updates.py
"""

from test_runs.redis_stand_ins import (
    FakeEngineStoreRedis,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_runner import (
    OrderEngine,
)
from unified_broker_interface.utilities.order_engine.utilities.order_update_follower import (
    ORDER_UPDATES_STREAM_KEY,
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


class StandInFollower:
    """Stands in for the order update follower: knows some orders, holds updates for others.

    Attributes:
        parents (dict): Each known broker order id, mapped to the parent whose leg it is.
        held (list): Updates for orders not known yet, as stream fields.
        replayed (int): How many held updates were applied once their order was known.
    """

    def __init__(self):
        """Builds the follower with no orders known and nothing held.

        Returns:
            None: This method returns nothing.
        """
        self.parents = {}
        self.held = []
        self.replayed = 0

    def learn(self, broker_order_id, parent):
        """Starts knowing one broker order id, as the broker's answer to a placement would.

        Args:
            broker_order_id (str): The broker's order id.
            parent (ParentOrder): The parent whose leg it is.

        Returns:
            None: This method returns nothing.
        """
        self.parents[broker_order_id] = parent

    def follow(self, fields):
        """Applies one update to the leg it names, holding it when the order is not known yet.

        Args:
            fields (dict): The stream entry's fields, with `order_id`, `status` and `filled_quantity`.

        Returns:
            ParentOrder | None: The changed parent, or None when the update named no known leg.

        Raises:
            ValueError: When the filled quantity is not a number.
        """
        parent = self.parents.get(fields['order_id'])
        if parent is None:
            self.held.append(fields)
            return None
        leg = parent.legs[0]
        leg.filled_quantity = int(fields['filled_quantity'])
        leg.state = fields['status']
        if leg.state == 'filled':
            parent.state = 'completed'
        return parent

    def replay_early_updates(self):
        """Applies every held update whose order is now known.

        Returns:
            list: The parents changed.
        """
        still_held = []
        changed = []
        for fields in self.held:
            if fields['order_id'] in self.parents:
                changed.append(self.follow(fields))
                self.count_replayed()
            else:
                still_held.append(fields)
        self.held = still_held
        return changed

    def count_replayed(self):
        """Counts one held update applied.

        Returns:
            None: This method returns nothing.
        """
        self.replayed = self.replayed + 1


class StandInReconciler:
    """Stands in for the book reconciler, answering with one change the socket missed.

    Attributes:
        missed (list): The changes to report, as `(parent_order_id, broker, fields)`.
    """

    def __init__(self, missed):
        """Builds the reconciler.

        Args:
            missed (list): The changes to report.

        Returns:
            None: This method returns nothing.
        """
        self.missed = missed

    def missed_updates(self):
        """The changes the polled books show and no socket delivered.

        Returns:
            list: The changes, as `(parent_order_id, broker, fields)`.
        """
        return list(self.missed)


class StandInDayRoll:
    """Stands in for the day roll, counting how often the caches were rebuilt.

    Attributes:
        rolls (int): How many times the caches were rebuilt.
    """

    def __init__(self):
        """Builds the day roll.

        Returns:
            None: This method returns nothing.
        """
        self.rolls = 0

    def roll(self):
        """Rebuilds the parent caches, which the stand-in only counts.

        Returns:
            None: This method returns nothing.
        """
        self.rolls = self.rolls + 1


class PrintingLogger:
    """A stand-in logger that prints what the engine logs.

    Attributes:
        prefix (str): What each printed line starts with.
    """

    def __init__(self):
        """Builds the logger.

        Returns:
            None: This method returns nothing.
        """
        self.prefix = '[log]'

    def exception(self, message):
        """Prints an error logged while handling an exception.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'{self.prefix} {message}')


class FollowingBrokerOrderUpdatesExample:
    """Applies, holds, replays and reconciles order updates and prints the parents the engine saved.

    Attributes:
        cache (FakeEngineStoreRedis): The stand-in Redis.
        follower (StandInFollower): The stand-in follower.
        reconciler (StandInReconciler): The stand-in reconciler.
        day_roll (StandInDayRoll): The stand-in day roll.
        engine (OrderEngine): The engine being shown.
    """

    def __init__(self):
        """Builds the engine with three open parents, each with one leg at Zerodha.

        Returns:
            None: This method returns nothing.
        """
        self.cache = FakeEngineStoreRedis()
        self.follower = StandInFollower()
        self.follower.learn('260930000001', self.parent('buy_now'))
        self.follower.learn('260930000003', self.parent('missed_by_socket'))
        self.reconciler = StandInReconciler([
            (
                'missed_by_socket',
                'zerodha',
                self.update('260930000003', 'filled', 5),
            ),
        ])
        self.day_roll = StandInDayRoll()
        self.engine = OrderEngine(
            self.cache,
            None,
            None,
            PrintingLogger(),
            30.0,
            300,
            None,
            ParentStore(self.cache),
            self.follower,
            day_roll=self.day_roll,
            reconciler=self.reconciler,
        )

    def parent(self, name):
        """One open parent with one acknowledged leg of ten shares.

        Args:
            name (str): The parent's id.

        Returns:
            ParentOrder: The parent.
        """
        parent = ParentOrder(name)
        parent.synthetic_type = 'simple'
        parent.state = 'working'
        leg = OrderLeg(f'{name}:1', 'entry')
        leg.broker = 'zerodha'
        leg.state = 'acknowledged'
        leg.quantity = 10
        parent.legs.append(leg)
        return parent

    def update(self, order_id, status, filled_quantity):
        """One entry of the order update stream.

        Args:
            order_id (str): The broker's order id.
            status (str): The leg state the update reports.
            filled_quantity (int | str): How much has filled.

        Returns:
            dict: The stream entry's fields.
        """
        return {
            'broker': 'zerodha',
            'order_id': order_id,
            'status': status,
            'filled_quantity': filled_quantity,
        }

    def add(self, fields):
        """Writes one update to the stream and marks it delivered, as a read would.

        Args:
            fields (dict): The stream entry's fields.

        Returns:
            str: The entry's id.
        """
        entry_id = self.cache.xadd(ORDER_UPDATES_STREAM_KEY, fields)
        self.cache.pending.setdefault(ORDER_UPDATES_STREAM_KEY, []).append(entry_id)
        return entry_id

    def show(self, name):
        """Prints one parent as the engine saved it to Redis.

        Args:
            name (str): The parent's id.

        Returns:
            None: This method returns nothing.
        """
        document = self.engine.parent_store.parent(name)
        if document is None:
            print(f'  {name}: not saved')
            return
        leg = document['legs'][0]
        print(f'  {name}: {document["state"]}, leg {leg["state"]} with {leg["filled_quantity"]} filled')

    def run(self):
        """Feeds the updates through each path and prints the saved parents after each.

        Returns:
            None: This method returns nothing.
        """
        print(f'Streams read: {self.engine.streams()}')

        arriving = [
            self.update('260930000001', 'partially_filled', 4),
            self.update('260930000002', 'acknowledged', 0),
            self.update('999999999999', 'filled', 1),
        ]
        for fields in arriving:
            self.engine.take_update(self.add(fields), fields)
        print('After three updates, one for a known order and two for orders not known yet:')
        self.show('buy_now')
        self.show('early_answer')
        print(f'  held: {len(self.follower.held)}')

        broken = self.update('260930000001', 'partially_filled', 'four')
        self.engine.apply_update(self.add(broken), broken)
        print(f'Unacknowledged update entries: {self.cache.pending[ORDER_UPDATES_STREAM_KEY]}')

        self.follower.learn('260930000002', self.parent('early_answer'))
        self.engine.take_early_updates()
        print('After the broker answered with order 260930000002:')
        self.show('early_answer')
        print(f'  held: {len(self.follower.held)}, replayed: {self.follower.replayed}')

        self.engine.replay_early_updates()
        print(f'Replaying again changes nothing: held {len(self.follower.held)}, replayed {self.follower.replayed}')

        self.engine.apply_replayed_update(self.update('260930000001', 'filled', 10))
        print(f'After a held fill for buy_now is applied, replayed {self.follower.replayed}:')
        self.show('buy_now')

        self.engine.reconcile_books()
        print('After the polled book showed a fill of 5 that no socket delivered:')
        self.show('missed_by_socket')
        self.engine.apply_reconciled_update(self.update('260930000003', 'filled', 10))
        print('After the next pass found all 10 filled:')
        self.show('missed_by_socket')

        self.engine.roll_day(None)
        print(f'Day rolls: {self.day_roll.rolls}')


if __name__ == '__main__':
    FollowingBrokerOrderUpdatesExample().run()
