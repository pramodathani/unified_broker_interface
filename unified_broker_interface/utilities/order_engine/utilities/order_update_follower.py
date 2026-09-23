"""Keeping a parent's legs in step with what the brokers say their orders are doing."""

import datetime
import json

from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)

ORDER_UPDATES_STREAM_KEY = 'unified:order-updates:stream'
ORDER_UPDATES_STREAM_FIELD = 'update'
LEG_STATES_FROM_STATUS = {
    'PENDING': 'acknowledged',
    'OPEN': 'acknowledged',
    'COMPLETE': 'filled',
    'CANCELLED': 'cancelled',
    'REJECTED': 'rejected',
    'EXPIRED': 'cancelled',
}


class OrderUpdateFollower:
    """Turns every broker's order updates into changes to the legs the engine owns.

    `bin/unified/orders/websocket_order_details` already collects every broker's order updates into one stream in one contract. The engine reads that stream rather than any broker's, so it learns about a fill the same way and at the same moment as everything else in the system, and adding a broker teaches the engine nothing new.

    Most updates on that stream are not the engine's business: they are orders placed from a broker's own app or website, or before the engine existed. An update is the engine's only when `unified:orders:children` names a parent for its broker and order id, and anything else is acknowledged and dropped.

    Attributes:
        parent_store (ParentStore): The Redis copy of the parents.
        event_log (SyntheticOrderEventLog): The record.
        logger (logging.Logger): The logger.
        followed (int): How many updates changed a leg.
        ignored (int): How many updates belonged to nobody.
    """

    def __init__(self, parent_store, event_log, logger, gates=None):
        """Builds the follower.

        Args:
            parent_store (ParentStore): The Redis copy of the parents.
            event_log (SyntheticOrderEventLog): The record.
            logger (logging.Logger): The logger.
            gates (RiskGates | None): The limits, which are told when an order trades.

        Returns:
            None: This method returns nothing.
        """
        self.parent_store = parent_store
        self.event_log = event_log
        self.logger = logger
        self.gates = gates
        self.followed = 0
        self.ignored = 0

    def follow(self, fields):
        """Applies one update from the stream to the leg it belongs to, if any.

        Args:
            fields (dict): The stream entry's fields.

        Returns:
            ParentOrder | None: The parent that changed, or None when the update was not the engine's.
        """
        update = self.decode(fields)
        if update is None:
            self.ignored = self.ignored + 1
            return None
        broker = update.get('broker')
        broker_order_id = update.get('order_id')
        if not broker or not broker_order_id:
            self.ignored = self.ignored + 1
            return None

        parent_order_id = self.parent_store.parent_for_broker_order(
            broker,
            str(broker_order_id),
        )
        if not parent_order_id:
            self.ignored = self.ignored + 1
            return None

        parent = self.read_parent(parent_order_id)
        if parent is None:
            self.ignored = self.ignored + 1
            return None
        leg = parent.leg_by_broker_order(broker, str(broker_order_id))
        if leg is None:
            self.ignored = self.ignored + 1
            return None

        changes = self.changes(leg, update)
        if not changes:
            self.ignored = self.ignored + 1
            return None

        self.record(parent, leg, update, changes)
        if self.gates is not None and changes.get('leg_state') == 'filled':
            self.gates.count_traded(leg.broker)
        self.followed = self.followed + 1
        return parent

    def read_parent(self, parent_order_id):
        """The parent with an id, rebuilt from its Redis record.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            ParentOrder | None: The parent.
        """
        document = self.parent_store.parent(parent_order_id)
        if document is None:
            return None
        return ParentOrder.from_document(document)

    def decode(self, fields):
        """One stream entry's update document.

        Args:
            fields (dict): The stream entry's fields.

        Returns:
            dict | None: The update, or None when the entry does not hold one.
        """
        try:
            update = json.loads(
                (fields or {}).get(ORDER_UPDATES_STREAM_FIELD),
            )
        except (TypeError, ValueError):
            return None
        if not isinstance(update, dict):
            return None
        return update

    def changes(self, leg, update):
        """What this update changes about the leg, or nothing.

        An update carrying no change is dropped rather than recorded. A broker's websocket repeats an order's state freely, and recording every repeat would fill the event log with rows saying nothing happened, which is the one thing that would make the log too slow to read back on start.

        Args:
            leg (OrderLeg): The leg the update belongs to.
            update (dict): The update, on the order contract.

        Returns:
            dict: The leg's fields that differ, empty when none do.
        """
        changes = {}
        status = str(update.get('status') or '').upper()
        state = LEG_STATES_FROM_STATUS.get(status)
        if state and state != leg.state:
            changes['leg_state'] = state
        filled_quantity = update.get('filled_quantity')
        if filled_quantity is not None and filled_quantity != leg.filled_quantity:
            changes['filled_quantity'] = filled_quantity
        average_price = update.get('average_price')
        if average_price is not None and average_price != leg.average_price:
            changes['average_price'] = average_price
        exchange_order_id = update.get('exchange_order_id')
        if exchange_order_id and exchange_order_id != leg.exchange_order_id:
            changes['exchange_order_id'] = exchange_order_id
        return changes

    def record(self, parent, leg, update, changes):
        """Writes the change and applies it to the parent.

        Args:
            parent (ParentOrder): The parent.
            leg (OrderLeg): The leg.
            update (dict): The update the change came from.
            changes (dict): What the update changes.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Anything the database raises.
        """
        event = {
            'parent_order_id': parent.parent_order_id,
            'sequence': parent.next_sequence(),
            'time': datetime.datetime.now(datetime.timezone.utc),
            'event': 'leg_update',
            'synthetic_type': parent.synthetic_type,
            'parent_state': parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'status_message': update.get('status_message'),
            'detail': {
                'status': update.get('status'),
            },
        }
        event.update(changes)
        self.event_log.record(event)
        parent.apply_event(event)
