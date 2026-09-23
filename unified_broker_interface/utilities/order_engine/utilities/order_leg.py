"""One order the engine actually sends to a broker on a parent order's behalf."""

LEG_STATES = (
    'planned',
    'sending',
    'sent',
    'acknowledged',
    'partially_filled',
    'filled',
    'rejected',
    'cancelled',
    'unknown',
)
FINISHED_LEG_STATES = (
    'filled',
    'rejected',
    'cancelled',
)


class OrderLeg:
    """One broker order belonging to a parent, and what is known about it.

    `sending` is the state that matters. It is written down and committed before the request leaves the machine, so a leg found in it after a restart means an order may exist at the broker that the engine never heard the answer to.

    Attributes:
        leg_id (str): This leg's id, the parent's id and a counter.
        role (str): What the leg is for: `entry`, `stop`, `target`, `slice` or `chase`.
        state (str): One of `LEG_STATES`.
        instrument_id (str | None): The instrument this leg trades, which is the parent's own except in a parent that spans several.
        broker (str | None): The broker it was sent to.
        broker_order_id (str | None): The broker's own order id, once it answered with one.
        exchange_order_id (str | None): The exchange's order id, once an update carried one.
        tag_sent (str | None): The tag that actually went to the broker, which is the caller's on an entry and the parent's own on a leg the engine invented.
        identifier_sent (str | None): The broker token or order symbol the request named the instrument by.
        transaction_type (str | None): BUY or SELL.
        product (str | None): The product on the shared vocabulary.
        order_type (str | None): The order type on the shared vocabulary.
        validity (str | None): The validity on the shared vocabulary.
        quantity (int | None): The quantity sent, in the broker's own terms.
        filled_quantity (int): How much has filled, in the broker's own terms.
        price (float | None): The limit price sent.
        trigger_price (float | None): The trigger price sent.
        average_price (float | None): The average fill price, once there is one.
        outcome (str | None): `accepted`, `rejected` or `unknown`, as the broker's answer was read.
        status_message (str | None): Why the outcome is not `accepted`.
        requested_at (str | None): When the leg was recorded as about to be sent.
        answered_at (str | None): When the broker's answer was recorded.
    """

    def __init__(self, leg_id, role):
        """Builds a leg that has not been sent.

        Args:
            leg_id (str): This leg's id.
            role (str): What the leg is for.

        Returns:
            None: This method returns nothing.
        """
        self.leg_id = leg_id
        self.role = role
        self.state = 'planned'
        self.instrument_id = None
        self.broker = None
        self.broker_order_id = None
        self.exchange_order_id = None
        self.tag_sent = None
        self.identifier_sent = None
        self.transaction_type = None
        self.product = None
        self.order_type = None
        self.validity = None
        self.quantity = None
        self.filled_quantity = 0
        self.price = None
        self.trigger_price = None
        self.average_price = None
        self.outcome = None
        self.status_message = None
        self.requested_at = None
        self.answered_at = None

    def is_finished(self):
        """Whether the broker can do nothing more with this leg.

        A leg in `unknown` is deliberately not finished: the engine does not know whether it is live, and treating it as done would leave a position unprotected.

        Returns:
            bool: True when the leg is filled, rejected or cancelled.
        """
        return self.state in FINISHED_LEG_STATES

    def is_live(self):
        """Whether this leg may still fill at the broker.

        Returns:
            bool: True when the broker has it and it is not finished.
        """
        return self.state in (
            'sent',
            'acknowledged',
            'partially_filled',
        )

    def document(self):
        """The leg as the parent's Redis record and the offline recording hold it.

        Returns:
            dict: Every attribute, all of them JSON types.
        """
        return {
            'leg_id': self.leg_id,
            'role': self.role,
            'instrument_id': self.instrument_id,
            'state': self.state,
            'broker': self.broker,
            'broker_order_id': self.broker_order_id,
            'exchange_order_id': self.exchange_order_id,
            'tag_sent': self.tag_sent,
            'identifier_sent': self.identifier_sent,
            'transaction_type': self.transaction_type,
            'product': self.product,
            'order_type': self.order_type,
            'validity': self.validity,
            'quantity': self.quantity,
            'filled_quantity': self.filled_quantity,
            'price': self.price,
            'trigger_price': self.trigger_price,
            'average_price': self.average_price,
            'outcome': self.outcome,
            'status_message': self.status_message,
            'requested_at': self.requested_at,
            'answered_at': self.answered_at,
        }

    @classmethod
    def from_document(cls, document):
        """Rebuilds a leg from the Redis record.

        Args:
            document (dict): The leg's document.

        Returns:
            OrderLeg: The leg.
        """
        leg = cls(document['leg_id'], document.get('role') or 'entry')
        for name, value in document.items():
            if name in ('leg_id', 'role'):
                continue
            if hasattr(leg, name):
                setattr(leg, name, value)
        return leg
