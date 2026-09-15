"""One order as a broker's order scripts keep it in Redis."""


class CancelNotReadyError(Exception):
    """A cancel that cannot be built yet because Redis does not hold a value the broker needs; its message is answered with HTTP 503."""


class StoredOrder:
    """One entry of a `<broker>:orders:orders` hash.

    Attributes:
        FINISHED_STATUSES (list): The statuses an order never leaves, so a cancel is refused without calling the broker.
        entry (dict): The whole entry.
        order (dict): The normalized order, or an empty dictionary when the entry has none.
        data (dict): The broker's own copy of the order, or an empty dictionary when the entry has none.
        status (str | None): The normalized status.
    """

    FINISHED_STATUSES = [
        'COMPLETE',
        'CANCELLED',
        'REJECTED',
        'EXPIRED',
    ]

    def __init__(self, entry):
        """Builds the stored order from a decoded hash entry.

        Args:
            entry (dict): The decoded entry.

        Returns:
            None: This method returns nothing.
        """
        self.entry = entry
        order = entry.get('order')
        if not isinstance(order, dict):
            order = {}
        data = entry.get('data')
        if not isinstance(data, dict):
            data = {}
        self.order = order
        self.data = data
        self.status = order.get('status')

    def is_finished(self):
        """Whether the order has reached a status that never changes back.

        Returns:
            bool: True for `COMPLETE`, `CANCELLED`, `REJECTED` and `EXPIRED`.
        """
        return self.status in self.FINISHED_STATUSES
