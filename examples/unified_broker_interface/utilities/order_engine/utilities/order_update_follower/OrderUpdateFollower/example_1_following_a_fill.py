"""Follows a broker's order updates for one plain limit order until it fills and its parent completes.

The order engine placed one leg at Zerodha for a parent order of type `simple`, and Zerodha's websocket now reports on it. Every update arrives the way `bin/unified/orders/websocket_order_details` writes it to `unified:order-updates:stream`: one stream entry whose `update` field is the order, as JSON, on the shared order contract.

The program feeds the follower five entries in turn. The first says the broker has the order open, the second repeats it word for word, the third says it filled, the fourth is about an order the engine never placed, and the fifth is not JSON at all. Before each one it asks `decode` for the update and `changes` for what that update would change about the leg, so the output shows why each entry was followed, ignored or held.

Three small stand-ins keep the program offline. `InMemoryParentStore` plays the Redis copy of the parents with two dictionaries, `ListEventLog` keeps each recorded event in a list instead of the PostgreSQL table, and `CountingGates` stands in for the risk gates and only counts the trades it is told about. The follower hands a changed leg to the order type only when it has a placement to pass on, and a `simple` order never uses it, so `UnusedPlacement` is an empty object.

Notice that the repeated update is ignored rather than recorded, that the fill both moves the leg to `filled` and lets the `simple` type complete the parent, and that the unknown order is held rather than dropped, because its own parent may just not be saved yet.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_update_follower/OrderUpdateFollower/example_1_following_a_fill.py
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

PARENT_ORDER_ID = '5b1f2c9e-3d4a-4e8b-9c1d-2a7f6e0b4c31'
BROKER_ORDER_ID = '250930000000417'


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


class CountingGates:
    """A stand-in for `RiskGates` that only counts the trades it is told about.

    Attributes:
        traded (list): The broker of every leg reported as filled.
    """

    def __init__(self):
        """Builds the gates with nothing counted.

        Returns:
            None: This method returns nothing.
        """
        self.traded = []

    def count_traded(self, broker_name):
        """Counts one filled order.

        Args:
            broker_name (str): The broker the order filled at.

        Returns:
            None: This method returns nothing.
        """
        self.traded.append(broker_name)


class UnusedPlacement:
    """A stand-in for `EnginePlacement` that a `simple` order never calls."""


class FollowingAFillExample:
    """Feeds one leg's updates to the follower and prints what each did.

    Attributes:
        parent_store (InMemoryParentStore): The stand-in parent store.
        event_log (ListEventLog): The stand-in event log.
        gates (CountingGates): The stand-in risk gates.
        follower (OrderUpdateFollower): The follower being shown.
    """

    def __init__(self):
        """Saves one working parent with one leg resting at Zerodha, and builds the follower.

        Returns:
            None: This method returns nothing.
        """
        self.parent_store = InMemoryParentStore()
        self.event_log = ListEventLog()
        self.gates = CountingGates()
        parent = ParentOrder(PARENT_ORDER_ID)
        parent.state = 'working'
        parent.instrument_id = '11111111-1111-5111-8111-000000000001'
        leg = OrderLeg(parent.next_leg_id(), 'entry')
        leg.state = 'sent'
        leg.broker = 'zerodha'
        leg.broker_order_id = BROKER_ORDER_ID
        leg.transaction_type = 'BUY'
        leg.order_type = 'LIMIT'
        leg.quantity = 10
        leg.price = 1415.5
        parent.legs.append(leg)
        parent.sequence = 3
        self.parent_store.save(parent)
        self.follower = OrderUpdateFollower(
            self.parent_store,
            self.event_log,
            logging.getLogger('example'),
            self.gates,
            UnusedPlacement(),
        )

    def entry(self, update):
        """Wraps one order update as a stream entry.

        Args:
            update (dict): The order, on the shared order contract.

        Returns:
            dict: The stream entry's fields.
        """
        return {
            'update': json.dumps(update),
        }

    def zerodha_update(self, status, filled_quantity, average_price):
        """Builds one Zerodha update for the leg.

        Args:
            status (str): The status on the shared vocabulary.
            filled_quantity (int): How much has filled.
            average_price (float | None): The average fill price.

        Returns:
            dict: The update.
        """
        return {
            'broker': 'zerodha',
            'order_id': BROKER_ORDER_ID,
            'exchange_order_id': '1100000047381925',
            'status': status,
            'status_message': None,
            'quantity': 10,
            'filled_quantity': filled_quantity,
            'average_price': average_price,
        }

    def run(self):
        """Feeds the five entries and prints the leg, the parent and the counters.

        Returns:
            None: This method returns nothing.
        """
        entries = [
            (
                'open',
                self.entry(self.zerodha_update('OPEN', 0, None)),
            ),
            (
                'open again',
                self.entry(self.zerodha_update('OPEN', 0, None)),
            ),
            (
                'filled',
                self.entry(self.zerodha_update('COMPLETE', 10, 1415.35)),
            ),
            (
                'someone else',
                self.entry({
                    'broker': 'dhan',
                    'order_id': '112509300000981',
                    'status': 'OPEN',
                }),
            ),
            (
                'not json',
                {
                    'update': 'not json',
                },
            ),
        ]
        for name, fields in entries:
            update = self.follower.decode(fields)
            print(f'--- {name}')
            if update is None:
                print('decoded: nothing readable')
            else:
                print(f'decoded: {update["broker"]} order {update["order_id"]} is {update["status"]}')
                parent = self.follower.read_parent(PARENT_ORDER_ID)
                leg = parent.leg_by_broker_order(update['broker'], update['order_id'])
                if leg is None:
                    print('no leg of this parent is that order')
                else:
                    print(f'would change: {self.follower.changes(leg, update)}')
            changed = self.follower.follow(fields)
            if changed is None:
                print('follow: nothing the engine owns changed')
                continue
            self.parent_store.save(changed)
            print(f'follow: parent is {changed.state}, leg is {changed.legs[0].state} with {changed.legs[0].filled_quantity} filled at {changed.legs[0].average_price}')

        print('--- afterwards')
        for event in self.event_log.events:
            print(f'event {event["sequence"]}: {event["event"]} leg_state={event.get("leg_state")} parent_state={event.get("parent_state")}')
        print(f'trades counted by the gates: {self.gates.traded}')
        print(f'followed={self.follower.followed} ignored={self.follower.ignored} held={self.follower.held} reacted={self.follower.reacted}')


if __name__ == '__main__':
    FollowingAFillExample().run()
