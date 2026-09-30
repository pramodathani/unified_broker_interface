"""Holds order updates that arrive before the engine has saved their order, and applies them once it has.

A broker can report an order filled before the engine has finished reading the answer to placing it, because the fill comes over a websocket while the placement's HTTP answer is still on its way. At that moment no parent owns the broker's order id yet, so the follower cannot apply the update. It holds it instead, in arrival order, for up to thirty seconds.

The program shows both ways the engine drains that hold. The first parent's two updates are found through `owning_parent`, as the engine's intake does when it only needs to know which worker thread to hand an update to, and are later taken back with `take_known_early_updates`, applied with `follow` and counted with `count_replayed`, as a worker thread does. The second parent's update is held by `follow` itself and applied in one step by `replay_early_updates`, which returns the parents it changed so the caller can save them.

`InMemoryParentStore` stands in for the Redis copy of the parents and `ListEventLog` for the event table, so nothing leaves the process. The follower is built without risk gates or a placement, so it records and applies each change but hands nothing to the order type.

Notice that a partial fill held before a full fill is applied first, because held updates keep their arrival order, and that nothing is taken back while the order is still unknown.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_update_follower/OrderUpdateFollower/example_2_updates_that_arrive_early.py
"""

import json
import logging

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.order_update_follower import (
    OrderUpdateFollower,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)

FIRST_PARENT_ID = '8c2d7e41-6a0b-4f3c-b5d2-91e4a7c0f615'
SECOND_PARENT_ID = 'e03a9b56-2c7d-4d18-8f6e-3b5a1c9d7e20'


class InMemoryParentStore:
    """A stand-in for `ParentStore` that keeps parents and their broker orders in dictionaries.

    Attributes:
        documents (dict): Parent order ids to their saved documents.
        children (dict): `broker:order_id` keys to the parent order id that owns them.
    """

    def __init__(self):
        """Builds an empty store.

        Returns:
            None: This method returns nothing.
        """
        self.documents = {}
        self.children = {}

    def save(self, parent):
        """Keeps one parent's document and the broker orders of its legs.

        Args:
            parent (ParentOrder): The parent to keep.

        Returns:
            None: This method returns nothing.
        """
        self.documents[parent.parent_order_id] = parent.document()
        for leg in parent.legs:
            if leg.broker and leg.broker_order_id:
                key = f'{leg.broker}:{leg.broker_order_id}'
                self.children[key] = parent.parent_order_id

    def parent_for_broker_order(self, broker, broker_order_id):
        """The parent that owns one broker order.

        Args:
            broker (str): The broker's name.
            broker_order_id (str): The broker's order id.

        Returns:
            str | None: The parent order id, or None when no parent owns it.
        """
        return self.children.get(f'{broker}:{broker_order_id}')

    def parents_for_broker_orders(self, keys):
        """The parents that own several broker orders.

        Args:
            keys (list): `broker:order_id` keys.

        Returns:
            list: One parent order id (str or None) per key, in the same order.
        """
        owners = []
        for key in keys:
            owners.append(self.children.get(key))
        return owners

    def parent(self, parent_order_id):
        """One saved parent's document.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            dict | None: The document, or None when it was never saved.
        """
        return self.documents.get(parent_order_id)


class ListEventLog:
    """A stand-in for `SyntheticOrderEventLog` that keeps events in a list.

    Attributes:
        events (list): Every event recorded, oldest first.
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


class UpdatesThatArriveEarlyExample:
    """Delivers fills before their orders are known, then makes the orders known and drains the hold.

    Attributes:
        parent_store (InMemoryParentStore): The stand-in parent store.
        event_log (ListEventLog): The stand-in event log.
        follower (OrderUpdateFollower): The follower being shown.
    """

    def __init__(self):
        """Builds the store, the log and a follower with no gates and no placement.

        Returns:
            None: This method returns nothing.
        """
        self.parent_store = InMemoryParentStore()
        self.event_log = ListEventLog()
        self.follower = OrderUpdateFollower(
            self.parent_store,
            self.event_log,
            logging.getLogger('example'),
        )

    def entry(self, broker, order_id, status, filled_quantity, average_price):
        """Builds one stream entry holding an order update.

        Args:
            broker (str): The broker's name.
            order_id (str): The broker's order id.
            status (str): The status on the shared vocabulary.
            filled_quantity (int): How much has filled.
            average_price (float): The average fill price.

        Returns:
            dict: The stream entry's fields.
        """
        return {
            'update': json.dumps({
                'broker': broker,
                'order_id': order_id,
                'status': status,
                'filled_quantity': filled_quantity,
                'average_price': average_price,
            }),
        }

    def working_parent(self, parent_order_id, broker, broker_order_id, quantity):
        """Builds a working parent whose one leg the broker has just accepted.

        Args:
            parent_order_id (str): The parent's id.
            broker (str): The broker the leg went to.
            broker_order_id (str): The broker's order id for the leg.
            quantity (int): The leg's quantity.

        Returns:
            ParentOrder: The parent.
        """
        parent = ParentOrder(parent_order_id)
        parent.state = 'working'
        leg = OrderLeg(parent.next_leg_id(), 'entry')
        leg.state = 'sent'
        leg.broker = broker
        leg.broker_order_id = broker_order_id
        leg.quantity = quantity
        parent.legs.append(leg)
        return parent

    def run(self):
        """Holds the early updates, makes their orders known and applies them both ways.

        Returns:
            None: This method returns nothing.
        """
        print('--- the first parent, through owning_parent and take_known_early_updates')
        partial = self.entry('fyers', '26093000000131', 'OPEN', 40, 2987.1)
        complete = self.entry('fyers', '26093000000131', 'COMPLETE', 75, 2987.4)
        for fields in (
            partial,
            complete,
        ):
            print(f'owning_parent: {self.follower.owning_parent(fields)}')
        print(f'held so far: {self.follower.held}')
        print(f'taken while the order is unknown: {self.follower.take_known_early_updates()}')

        self.parent_store.save(
            self.working_parent(FIRST_PARENT_ID, 'fyers', '26093000000131', 75),
        )
        taken = self.follower.take_known_early_updates()
        print(f'taken once the parent is saved: {len(taken)}')
        for parent_order_id, broker, fields in taken:
            update = self.follower.decode(fields)
            print(f'  for parent {parent_order_id} at {broker}: {update["status"]} with {update["filled_quantity"]} filled')
            changed = self.follower.follow(fields)
            self.follower.count_replayed()
            self.parent_store.save(changed)
            print(f'  leg is now {changed.legs[0].state} with {changed.legs[0].filled_quantity} filled')

        print('--- the second parent, through follow and replay_early_updates')
        early = self.entry('dhan', '112509300000502', 'COMPLETE', 1, 24.85)
        print(f'follow before the parent is saved: {self.follower.follow(early)}')
        print(f'replayed before the parent is saved: {self.follower.replay_early_updates()}')
        self.parent_store.save(
            self.working_parent(SECOND_PARENT_ID, 'dhan', '112509300000502', 1),
        )
        for changed in self.follower.replay_early_updates():
            self.parent_store.save(changed)
            print(f'replayed: parent {changed.parent_order_id} leg is {changed.legs[0].state} at {changed.legs[0].average_price}')

        print('--- afterwards')
        for event in self.event_log.events:
            print(f'{event["parent_order_id"]} event {event["sequence"]}: {event["event"]} leg_state={event.get("leg_state")} filled_quantity={event.get("filled_quantity")}')
        print(f'followed={self.follower.followed} held={self.follower.held} replayed={self.follower.replayed} ignored={self.follower.ignored}')


if __name__ == '__main__':
    UpdatesThatArriveEarlyExample().run()
