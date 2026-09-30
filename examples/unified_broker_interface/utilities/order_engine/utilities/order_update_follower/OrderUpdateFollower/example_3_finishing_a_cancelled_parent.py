"""Records a broker's cancel confirmation on a parent that is being cancelled, and lets the order type finish it.

`follow` does four things with an update it owns: it works out the `changes`, it `record`s them, it tells the risk gates about a fill and it hands the change to the order type through `react`. This program calls `record` and `react` directly, so each step can be seen on its own.

The parent is a `simple` order that a caller asked to cancel, so it is in state `cancelling` while its one leg still rests at Kotak. Kotak then confirms the cancel. Recording the change moves the leg to `cancelled` in the event log and in the parent in memory. Reacting is what ends the parent: for a parent in `cancelling`, the order type checks that no leg is still resting and records the parent as `cancelled`.

The program reacts twice, first with a follower built without a placement and then with one built with a placement. A follower with no placement never reacts, which is how the offline suites and tools that only want the record use it. `UnusedPlacement` is an empty stand-in, because finishing a cancel sends nothing to a broker. `InMemoryParentStore` stands in for the Redis copy of the parents and `ListEventLog` for the event table.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_update_follower/OrderUpdateFollower/example_3_finishing_a_cancelled_parent.py
"""

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

PARENT_ORDER_ID = '41d6b8a2-9e3f-4c75-a0b1-7f2e5d8c6a94'


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


class UnusedPlacement:
    """A stand-in for `EnginePlacement` that finishing a cancel never calls."""


class FinishingACancelledParentExample:
    """Records a cancel confirmation and reacts to it with and without a placement.

    Attributes:
        parent_store (InMemoryParentStore): The stand-in parent store.
        event_log (ListEventLog): The stand-in event log.
        recording_follower (OrderUpdateFollower): A follower with no placement, which records but never reacts.
        reacting_follower (OrderUpdateFollower): A follower with a placement, which also reacts.
    """

    def __init__(self):
        """Builds the store, the log and both followers.

        Returns:
            None: This method returns nothing.
        """
        self.parent_store = InMemoryParentStore()
        self.event_log = ListEventLog()
        logger = logging.getLogger('example')
        self.recording_follower = OrderUpdateFollower(
            self.parent_store,
            self.event_log,
            logger,
        )
        self.reacting_follower = OrderUpdateFollower(
            self.parent_store,
            self.event_log,
            logger,
            None,
            UnusedPlacement(),
        )

    def cancelling_parent(self):
        """Builds a parent a caller asked to cancel, whose one leg still rests at Kotak.

        Returns:
            ParentOrder: The parent.
        """
        parent = ParentOrder(PARENT_ORDER_ID)
        parent.state = 'cancelling'
        parent.sequence = 5
        leg = OrderLeg(parent.next_leg_id(), 'entry')
        leg.state = 'acknowledged'
        leg.broker = 'kotak'
        leg.broker_order_id = '260930000118742'
        leg.quantity = 50
        leg.price = 612.25
        parent.legs.append(leg)
        return parent

    def run(self):
        """Records the cancel, reacts without and with a placement, and prints the parent after each step.

        Returns:
            None: This method returns nothing.
        """
        parent = self.cancelling_parent()
        leg = parent.legs[0]
        update = {
            'broker': 'kotak',
            'order_id': '260930000118742',
            'status': 'CANCELLED',
            'status_message': 'Cancelled by user',
            'filled_quantity': 0,
        }
        changes = self.recording_follower.changes(leg, update)
        print(f'changes: {changes}')

        self.recording_follower.record(parent, leg, update, changes)
        print(f'after record: parent is {parent.state}, leg is {leg.state}, sequence {parent.sequence}')

        self.recording_follower.react(parent, leg, changes)
        print(f'after react with no placement: parent is {parent.state}')

        self.reacting_follower.react(parent, leg, changes)
        print(f'after react with a placement: parent is {parent.state}')
        saved = self.parent_store.parent(PARENT_ORDER_ID)
        print(f'saved copy: state {saved["state"]}, broker orders it owns {self.parent_store.children}')

        for event in self.event_log.events:
            print(f'event {event["sequence"]}: {event["event"]} leg_state={event.get("leg_state")} parent_state={event.get("parent_state")} status_message={event.get("status_message")!r}')


if __name__ == '__main__':
    FinishingACancelledParentExample().run()
