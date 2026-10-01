"""The execution that shows nothing and strikes only when enough size is displayed at an acceptable price."""


class BookDepthExecution:
    """A plan order's execution that sends nothing until the other side of the book shows at least `minimum_quantity` at or inside `limit_price`, then strikes for what is there.

    It keeps the rules of today's liquidity-seeking type. It adds up the displayed quantity at every level of the opposite side that is no worse than the limit, and when that reaches the minimum it sends the smaller of what is shown and what is left. A strike that only partly fills rests at its limit, and the next strike is only for what is neither traded nor resting. A strike the broker rejects stops the order. The size shown is the size displayed, so more or less than that may fill.

    Attributes:
        limit_price (decimal.Decimal): The worst price it will trade at.
        minimum_quantity (int): The displayed size that makes a strike worthwhile.
    """

    def __init__(self, limit_price, minimum_quantity):
        """Builds the execution from settings the plan reader has already checked.

        Args:
            limit_price (decimal.Decimal): The worst price it will trade at.
            minimum_quantity (int): The displayed size that makes a strike worthwhile.

        Returns:
            None: This method returns nothing.
        """
        self.limit_price = limit_price
        self.minimum_quantity = minimum_quantity

    def needs_prices(self):
        """Whether this execution reads quotes, which it does, for the book.

        Returns:
            bool: True.
        """
        return True

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does, when size appears.

        Returns:
            bool: True.
        """
        return True

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing a resting order, which it is not; later strikes are larger.

        Returns:
            bool: False.
        """
        return False

    def begin(self, plan_order, memory, quotes, now):
        """Readies the execution, which needs nothing.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): Unused.
            quotes (dict): Unused.
            now (float): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory, quotes, now

    def reachable_quantity(self, view, sending_side):
        """The displayed quantity on the opposite side at prices no worse than the limit.

        Args:
            view (MarketView): The order's quote.
            sending_side (str): BUY or SELL, the side the order is sent on.

        Returns:
            int: The quantity.
        """
        if not view.is_readable():
            return 0
        depth = view.quote.get('depth')
        if not isinstance(depth, dict):
            return 0
        if sending_side == 'BUY':
            levels = depth.get('sell')
        else:
            levels = depth.get('buy')
        if not isinstance(levels, list):
            return 0
        total = 0
        for entry in levels:
            if not isinstance(entry, dict):
                continue
            price = view.number(entry.get('price'))
            if price is None:
                continue
            if sending_side == 'BUY' and price > self.limit_price:
                continue
            if sending_side == 'SELL' and price < self.limit_price:
                continue
            try:
                total = total + int(entry.get('quantity') or 0)
            except (TypeError, ValueError):
                continue
        return total

    def committed(self, pieces):
        """How much the pieces sent so far account for: what filled of a finished piece, and the whole of a resting one.

        Args:
            pieces (list): The broker orders sent so far.

        Returns:
            int: The quantity.
        """
        total = 0
        for piece in pieces:
            if piece.is_finished():
                total = total + (piece.filled_quantity or 0)
            else:
                total = total + (piece.quantity or 0)
        return total

    def last_was_rejected(self, pieces):
        """Whether the broker rejected the last piece, which stops this execution, as a rejected piece stops an iceberg, rather than sending a fresh order on every tick.

        Args:
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True when the last piece was rejected.
        """
        return bool(pieces) and pieces[-1].state == 'rejected'

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now, sending_side=None):
        """A strike, when enough size shows at an acceptable price.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            memory (dict): Unused.
            total (int): The quantity the order should trade in all.
            pieces (list): The broker orders sent so far.
            quotes (dict): The quotes the tick carried.
            now (float): Unused.
            sending_side (str | None): BUY or SELL, the side the order is sent on.

        Returns:
            list: One quantity, or nothing.
        """
        del now
        remaining = total - self.committed(pieces)
        if not self.will_send_more(memory, remaining, pieces) or sending_side is None:
            return []
        available = self.reachable_quantity(plan_order.view(quotes), sending_side)
        if available < self.minimum_quantity:
            return []
        return [
            min(available, remaining),
        ]

    def will_send_more(self, memory, remaining, pieces):
        """Whether more strikes may still be sent: while some is neither traded nor resting, and the last strike was not rejected.

        Args:
            memory (dict): Unused.
            remaining (int): The quantity neither traded nor resting.
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True when another strike may follow.
        """
        del memory
        if self.last_was_rejected(pieces):
            return False
        return remaining > 0

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'book_depth': {
                'limit_price': str(self.limit_price),
                'minimum_quantity': self.minimum_quantity,
            },
        }
