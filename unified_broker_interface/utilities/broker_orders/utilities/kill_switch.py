"""Deciding what to cancel and what to close when everything has to be unwound at once."""

OPEN_STATUSES = (
    'PENDING',
    'OPEN',
)
CLOSING_SIDES = {
    True: 'SELL',
    False: 'BUY',
}


class KillSwitch:
    """Works out what has to be cancelled and what has to be closed, and in which order.

    It decides and does not act. The caller reads Redis and sends, so the rule that every Redis read the order routes make is in one module survives a panic button, and so this can be checked offline against order books and positions that never existed.

    **Cancelling comes first, and waiting for the cancels to be confirmed comes before closing.** A resting stop or target that is still live when a position is closed will fill afterwards and open a new position in the opposite direction, which turns an attempt to go flat into a fresh trade nobody chose. That ordering is the single most important thing in this class, and it is the reason the caller must wait rather than sending everything at once.

    Attributes:
        broker_names (list): Every broker's name.
    """

    def __init__(self, broker_names):
        """Builds the kill switch.

        Args:
            broker_names (list): Every broker's name.

        Returns:
            None: This method returns nothing.
        """
        self.broker_names = broker_names

    def orders_to_cancel(self, order_books):
        """Every order that is still live at a broker and so has to be cancelled first.

        An order whose status the brokers' shared vocabulary does not recognise is included rather than skipped. A status nobody has mapped is far more likely to be a live order at a broker that invented a spelling than a finished one, and cancelling something already finished costs a refusal, while leaving something live costs a position.

        Args:
            order_books (dict): Each broker's `<broker>:orders:orders` entries, decoded, by broker name.

        Returns:
            list: One dictionary per order, with `broker`, `order_id`, `status` and `entry`.
        """
        cancelling = []
        for broker_name in self.broker_names:
            entries = order_books.get(broker_name) or {}
            for order_id, entry in sorted(entries.items()):
                order = (entry or {}).get('order')
                if not isinstance(order, dict):
                    continue
                status = str(order.get('status') or '').upper()
                if self.is_finished(status):
                    continue
                cancelling.append({
                    'broker': broker_name,
                    'order_id': order_id,
                    'status': status,
                    'entry': entry,
                })
        return cancelling

    def is_finished(self, status):
        """Whether a status means the broker can do nothing more with the order.

        Args:
            status (str): The status on the shared vocabulary, uppercased.

        Returns:
            bool: True when the order is finished.
        """
        return status in (
            'COMPLETE',
            'CANCELLED',
            'REJECTED',
            'EXPIRED',
        )

    def still_open(self, order_books, cancelled):
        """Which of the orders asked to be cancelled a broker still reports as live.

        Args:
            order_books (dict): Each broker's entries, decoded, by broker name, read again.
            cancelled (list): What `orders_to_cancel` returned.

        Returns:
            list: The `(broker, order_id)` pairs still live.
        """
        waiting = []
        for order in cancelled:
            entries = order_books.get(order['broker']) or {}
            entry = entries.get(order['order_id'])
            current = (entry or {}).get('order')
            if not isinstance(current, dict):
                continue
            status = str(current.get('status') or '').upper()
            if not self.is_finished(status):
                waiting.append((order['broker'], order['order_id']))
        return waiting

    def positions_to_close(self, position_books):
        """Every position that is not flat, with the order that would close it.

        Positions are read from each broker rather than from the unified document, because that document merges a position across brokers and a closing order has to go to the broker that actually holds it.

        Only `NET` positions are closed. A broker reporting both bases reports the same holding twice, and closing on both would double the trade.

        Args:
            position_books (dict): Each broker's `<broker>:portfolio:positions` entries, decoded, by broker name.

        Returns:
            list: One dictionary per position, with `broker`, `instrument_token`, `tradingsymbol`, `product`, `quantity`, `transaction_type` and `close_quantity`.
        """
        closing = []
        for broker_name in self.broker_names:
            entries = position_books.get(broker_name) or {}
            for key, entry in sorted(entries.items()):
                position = (entry or {}).get('position')
                if not isinstance(position, dict):
                    continue
                basis = str(position.get('day_or_net') or 'NET').upper()
                if basis != 'NET':
                    continue
                quantity = self.whole(position.get('quantity'))
                if not quantity:
                    continue
                closing.append({
                    'broker': broker_name,
                    'position_key': key,
                    'instrument_token': position.get('instrument_token'),
                    'tradingsymbol': position.get('tradingsymbol'),
                    'exchange': position.get('exchange'),
                    'segment': position.get('segment'),
                    'product': position.get('product'),
                    'quantity': quantity,
                    'transaction_type': CLOSING_SIDES[quantity > 0],
                    'close_quantity': abs(quantity),
                })
        return closing

    def still_held(self, position_books, closed):
        """Which of the positions sent a closing order a broker still reports as held.

        A position is held while its entry is still in the broker's hash with a quantity other than zero. An entry that has disappeared counts as closed, in the same way that `still_open` treats an order whose entry has gone.

        Args:
            position_books (dict): Each broker's positions entries, decoded, by broker name, read again.
            closed (list): The entries from `positions_to_close` whose closing order was accepted.

        Returns:
            list: The `(broker, position_key)` pairs still held.
        """
        held = []
        for position in closed:
            entries = position_books.get(position['broker']) or {}
            entry = entries.get(position['position_key'])
            current = (entry or {}).get('position')
            if not isinstance(current, dict):
                continue
            if self.whole(current.get('quantity')):
                held.append((position['broker'], position['position_key']))
        return held

    def whole(self, value):
        """A signed quantity as an integer, or zero when it cannot be read.

        Args:
            value (object): The value.

        Returns:
            int: The quantity.
        """
        if value is None:
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
