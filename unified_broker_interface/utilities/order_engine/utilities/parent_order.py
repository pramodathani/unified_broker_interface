"""One order a caller asked for, and the state machine every order type runs through."""

from unified_broker_interface.utilities.order_engine.utilities.order_leg import OrderLeg

PARENT_STATES = (
    'received',
    'working',
    'protecting',
    'completed',
    'cancelled',
    'rejected',
    'failed',
)
TERMINAL_PARENT_STATES = (
    'completed',
    'cancelled',
    'rejected',
    'failed',
)
ALLOWED_CHANGES = {
    'received': (
        'working',
        'rejected',
        'failed',
        'cancelled',
    ),
    'working': (
        'protecting',
        'completed',
        'cancelled',
        'failed',
    ),
    'protecting': (
        'completed',
        'cancelled',
        'failed',
    ),
}


class ParentOrder:
    """One order a caller asked for, however many broker orders it takes to run it.

    A plain limit order is the degenerate path through this machine: it is received, one leg is placed, the leg fills and the parent is done. A bracket runs further through the same states, with its entry filling into `protecting` while a stop and a target rest at the broker.

    Every change goes through `apply_event`, and so does recovery. The engine writes an event, commits it and then applies it; on start it reads the day's events back and applies them in the same order through the same method. That is deliberate: the path that rebuilds state after a restart is exercised by every order all day, so it cannot quietly stop working.

    `failed` means a human has to look. The engine never retries out of it and never arms protective legs for a parent in it, because a parent reaches `failed` exactly when the engine does not know what the broker has.

    Attributes:
        parent_order_id (str): This parent's id.
        parent_tag (str): The short tag a leg the engine invents carries to the broker.
        intent_id (str | None): The intent the REST API wrote.
        synthetic_type (str): The kind of order, `simple` for a plain one.
        state (str): One of `PARENT_STATES`.
        instrument_id (str | None): The instrument every leg is for.
        tag (str | None): The caller's own tag, echoed back in the answer.
        body (dict): The caller's request body, kept so a later leg can be built from it.
        parameters (dict): What the order type needs beside the body, such as a stop price.
        legs (list): The `OrderLeg` objects, in the order they were created.
        sequence (int): The last sequence number written for this parent.
        created_at (str | None): When the parent was received.
        updated_at (str | None): When the last event was applied.
        last_error (str | None): Why the parent last failed, for a person reading it back.
    """

    def __init__(self, parent_order_id, parent_tag=None):
        """Builds a parent with no legs and nothing yet done.

        Args:
            parent_order_id (str): This parent's id.
            parent_tag (str | None): The short tag for legs the engine invents; the first sixteen characters of the id when not given.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = parent_order_id
        self.parent_tag = parent_tag or self.tag_from_id(parent_order_id)
        self.intent_id = None
        self.synthetic_type = 'simple'
        self.state = 'received'
        self.instrument_id = None
        self.tag = None
        self.body = {}
        self.parameters = {}
        self.legs = []
        self.sequence = 0
        self.created_at = None
        self.updated_at = None
        self.last_error = None

    def tag_from_id(self, parent_order_id):
        """The broker-side tag for a leg the engine invents.

        `PlaceOrderRequest` validates a tag as one to twenty letters and digits, so the hyphens of a UUID have to go and only part of it fits. Sixteen hexadecimal characters is well inside the limit and far more than enough to tell one day's parents apart.

        Args:
            parent_order_id (str): This parent's id.

        Returns:
            str: The tag.
        """
        return str(parent_order_id).replace('-', '')[:16]

    def next_sequence(self):
        """The sequence number the next event for this parent takes.

        Returns:
            int: One more than the last, counting from 1.
        """
        return self.sequence + 1

    def is_terminal(self):
        """Whether the parent has finished and needs nothing more.

        Returns:
            bool: True when the state is one of `TERMINAL_PARENT_STATES`.
        """
        return self.state in TERMINAL_PARENT_STATES

    def can_change_to(self, state):
        """Whether the parent may move to a state from the one it is in.

        This is consulted where the engine decides what to do next. It is deliberately not consulted by `apply_event`, because recovery must be able to replay whatever was recorded, including a history written by a version of the engine that allowed something this one does not.

        Args:
            state (str): The state being considered.

        Returns:
            bool: True when the change is allowed.
        """
        return state in ALLOWED_CHANGES.get(self.state, ())

    def leg(self, leg_id):
        """The leg with an id, or None.

        Args:
            leg_id (str): The leg's id.

        Returns:
            OrderLeg | None: The leg.
        """
        for leg in self.legs:
            if leg.leg_id == leg_id:
                return leg
        return None

    def leg_by_broker_order(self, broker, broker_order_id):
        """The leg a broker's order id belongs to, or None.

        Args:
            broker (str): The broker's name.
            broker_order_id (str): The broker's order id.

        Returns:
            OrderLeg | None: The leg.
        """
        for leg in self.legs:
            if leg.broker == broker and leg.broker_order_id == broker_order_id:
                return leg
        return None

    def next_leg_id(self):
        """The id the next leg takes.

        Returns:
            str: The parent's id and a counter, counting from 1.
        """
        return f'{self.parent_order_id}:{len(self.legs) + 1}'

    def legs_in_state(self, state):
        """Every leg in one state.

        Args:
            state (str): The leg state.

        Returns:
            list: The legs.
        """
        found = []
        for leg in self.legs:
            if leg.state == state:
                found.append(leg)
        return found

    def live_legs(self):
        """Every leg the broker may still fill.

        Returns:
            list: The legs.
        """
        found = []
        for leg in self.legs:
            if leg.is_live():
                found.append(leg)
        return found

    def filled_quantity(self):
        """How much of the entry has filled, in the broker's own terms.

        Returns:
            int: The filled quantity across every entry leg.
        """
        total = 0
        for leg in self.legs:
            if leg.role == 'entry':
                total = total + (leg.filled_quantity or 0)
        return total

    def apply_event(self, event):
        """Applies one recorded transition, which is the only way this object changes.

        Args:
            event (dict): The event as `SyntheticOrderEventLog` writes it.

        Returns:
            None: This method returns nothing.
        """
        name = event.get('event')
        sequence = event.get('sequence')
        if isinstance(sequence, int) and sequence > self.sequence:
            self.sequence = sequence
        recorded_at = event.get('time')
        if recorded_at is not None:
            self.updated_at = str(recorded_at)

        if name == 'parent_received':
            self.apply_received(event)
        elif name in ('leg_requested', 'leg_answered', 'leg_update'):
            self.apply_to_leg(name, event)
        elif name == 'parent_state_changed':
            self.apply_state_change(event)
        elif name in ('orphan_attributed', 'orphan_abandoned'):
            self.apply_orphan(name, event)

    def apply_received(self, event):
        """Applies the event that starts a parent.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        self.synthetic_type = event.get('synthetic_type') or 'simple'
        self.state = event.get('parent_state') or 'received'
        self.intent_id = self.text(event.get('intent_id'))
        self.instrument_id = self.text(event.get('instrument_id'))
        detail = event.get('detail')
        if isinstance(detail, dict):
            self.body = detail.get('body') or {}
            self.parameters = detail.get('parameters') or {}
            self.tag = self.body.get('tag')
        if self.created_at is None:
            self.created_at = self.updated_at

    def apply_to_leg(self, name, event):
        """Applies an event that describes one leg, creating the leg when it is new.

        Args:
            name (str): The event's name.
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        leg_id = event.get('leg_id')
        if not leg_id:
            return
        leg = self.leg(leg_id)
        if leg is None:
            leg = OrderLeg(leg_id, event.get('leg_role') or 'entry')
            self.legs.append(leg)
        if event.get('leg_state'):
            leg.state = event['leg_state']
        for column, attribute in (
            ('instrument_id', 'instrument_id'),
            ('broker', 'broker'),
            ('broker_order_id', 'broker_order_id'),
            ('exchange_order_id', 'exchange_order_id'),
            ('tag_sent', 'tag_sent'),
            ('identifier_sent', 'identifier_sent'),
            ('transaction_type', 'transaction_type'),
            ('product', 'product'),
            ('order_type', 'order_type'),
            ('validity', 'validity'),
            ('quantity', 'quantity'),
            ('price', 'price'),
            ('trigger_price', 'trigger_price'),
            ('average_price', 'average_price'),
            ('outcome', 'outcome'),
            ('status_message', 'status_message'),
        ):
            value = event.get(column)
            if value is not None:
                setattr(leg, attribute, value)
        filled_quantity = event.get('filled_quantity')
        if filled_quantity is not None:
            leg.filled_quantity = filled_quantity
        if name == 'leg_requested':
            leg.requested_at = self.updated_at
        if name == 'leg_answered':
            leg.answered_at = self.updated_at

    def apply_state_change(self, event):
        """Applies a change of the parent's own state.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        state = event.get('parent_state')
        if state:
            self.state = state
        message = event.get('status_message')
        if message:
            self.last_error = message

    def apply_orphan(self, name, event):
        """Applies the outcome of trying to attribute a leg left in `sending` by a crash.

        The parent's own state is applied here as well as the leg's, because abandoning an orphan moves the parent to `failed`. Leaving that to the event's context would let a parent replay as `received` with an `unknown` leg: not terminal, so the open set keeps it, and not in `sending`, so nothing ever looks at it again.

        Args:
            name (str): The event's name.
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        self.apply_to_leg('leg_update', event)
        state = event.get('parent_state')
        if state:
            self.state = state
        if name == 'orphan_abandoned':
            self.last_error = event.get('status_message')

    def text(self, value):
        """A value as text, or None.

        Args:
            value (object): The value.

        Returns:
            str | None: The text.
        """
        if value is None:
            return None
        return str(value)

    def document(self):
        """The parent as its Redis record holds it.

        Returns:
            dict: Every field, all of them JSON types.
        """
        legs = []
        for leg in self.legs:
            legs.append(leg.document())
        return {
            'parent_order_id': self.parent_order_id,
            'parent_tag': self.parent_tag,
            'intent_id': self.intent_id,
            'synthetic_type': self.synthetic_type,
            'state': self.state,
            'instrument_id': self.instrument_id,
            'tag': self.tag,
            'body': self.body,
            'parameters': self.parameters,
            'legs': legs,
            'sequence': self.sequence,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'last_error': self.last_error,
        }

    @classmethod
    def from_document(cls, document):
        """Rebuilds a parent from its Redis record.

        Args:
            document (dict): The parent's document.

        Returns:
            ParentOrder: The parent.
        """
        parent = cls(document['parent_order_id'], document.get('parent_tag'))
        for name in (
            'intent_id',
            'synthetic_type',
            'state',
            'instrument_id',
            'tag',
            'body',
            'parameters',
            'sequence',
            'created_at',
            'updated_at',
            'last_error',
        ):
            if document.get(name) is not None:
                setattr(parent, name, document[name])
        for leg_document in document.get('legs') or []:
            parent.legs.append(OrderLeg.from_document(leg_document))
        return parent

    @classmethod
    def from_events(cls, events):
        """Rebuilds a parent by replaying its recorded transitions.

        A transition recorded twice is ignored, because the table has no unique constraint to prevent one and a duplicate changes nothing.

        Args:
            events (list): The parent's events, oldest first.

        Returns:
            ParentOrder | None: The parent, or None when the events name none.
        """
        parent = None
        applied = set()
        for event in events:
            parent_order_id = event.get('parent_order_id')
            if parent_order_id is None:
                continue
            if parent is None:
                parent = cls(str(parent_order_id))
            sequence = event.get('sequence')
            if sequence in applied:
                continue
            applied.add(sequence)
            parent.apply_event(event)
        return parent
