"""One leg the order engine sent to a broker, folded from its rows in `unified.synthetic_order_events`."""

TRANSACTION_TYPES = [
    'BUY',
    'SELL',
]


class LegExecution:
    """What happened to one leg: when it was decided on, sent and answered, and what filled at what price.

    Attributes:
        parent_order_id (str): The parent the leg belongs to.
        leg_id (str): The leg's id within its parent.
        decided_at (datetime.datetime): When the decision to trade was made: the parent's arrival for its first leg, and the leg's own request for every later one.
        synthetic_type (str | None): The parent's type, such as `simple` or `plan`.
        leg_role (str | None): What the leg is for, such as `entry` or `stop`.
        broker (str | None): The broker it was sent to.
        instrument_id (str | None): The instrument it trades.
        transaction_type (str | None): `BUY` or `SELL`.
        product (str | None): The product, such as `MIS`.
        order_type (str | None): The order type, such as `LIMIT`.
        quantity (int | None): The quantity asked for, in units.
        price (decimal.Decimal | None): The limit price the leg was sent with, or None for a market order.
        sent_at (datetime.datetime | None): When the engine recorded the request, just before sending it.
        answered_at (datetime.datetime | None): When the engine recorded the broker's answer.
        outcome (str | None): `accepted`, `rejected` or `unknown`.
        filled_quantity (int | None): The quantity filled, as the broker last reported it.
        average_price (decimal.Decimal | None): The average fill price, as the broker last reported it.
    """

    def __init__(self, parent_order_id, leg_id, decided_at):
        """Builds a leg with nothing known about it yet but its decision time.

        Args:
            parent_order_id (str): The parent the leg belongs to.
            leg_id (str): The leg's id within its parent.
            decided_at (datetime.datetime): When the decision to trade was made.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = parent_order_id
        self.leg_id = leg_id
        self.decided_at = decided_at
        self.synthetic_type = None
        self.leg_role = None
        self.broker = None
        self.instrument_id = None
        self.transaction_type = None
        self.product = None
        self.order_type = None
        self.quantity = None
        self.price = None
        self.sent_at = None
        self.answered_at = None
        self.outcome = None
        self.filled_quantity = None
        self.average_price = None

    def apply(self, event):
        """Takes in one of the leg's events; events of other kinds are ignored.

        A `leg_update` row carries only what changed, so a fill quantity or price is kept until a later row changes it.

        Args:
            event (dict): One row of `unified.synthetic_order_events`, by column name.

        Returns:
            None: This method returns nothing.
        """
        name = event.get('event')
        if name == 'leg_requested':
            self.sent_at = event.get('time')
            self.synthetic_type = event.get('synthetic_type')
            self.leg_role = event.get('leg_role')
            self.broker = event.get('broker')
            self.instrument_id = event.get('instrument_id')
            self.transaction_type = event.get('transaction_type')
            self.product = event.get('product')
            self.order_type = event.get('order_type')
            self.quantity = event.get('quantity')
            self.price = event.get('price')
        elif name == 'leg_answered':
            self.answered_at = event.get('time')
            self.outcome = event.get('outcome')
        elif name == 'leg_update':
            if event.get('filled_quantity') is not None:
                self.filled_quantity = event.get('filled_quantity')
            if event.get('average_price') is not None:
                self.average_price = event.get('average_price')

    def is_filled(self):
        """Whether the leg was sent and at least part of it filled at a known price.

        Returns:
            bool: True when there is a fill to measure.
        """
        if self.sent_at is None or self.instrument_id is None:
            return False
        if self.transaction_type not in TRANSACTION_TYPES:
            return False
        if not self.filled_quantity or self.filled_quantity <= 0:
            return False
        if self.average_price is None or self.average_price <= 0:
            return False
        return True

    def side(self):
        """The sign that turns a price move into a cost: a higher price costs a buyer and helps a seller.

        Returns:
            int: 1 for a buy and -1 for a sell.
        """
        if self.transaction_type == 'SELL':
            return -1
        return 1
