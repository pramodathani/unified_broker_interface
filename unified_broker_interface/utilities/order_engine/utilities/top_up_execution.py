"""The execution that sends a new order for whatever a join's growing target is missing, and never resizes a resting one."""


class TopUpExecution:
    """A plan order's execution that, each time its target grows, sends one new broker order for the quantity not yet traded or resting.

    It keeps the way today's attached hedge and legged spread grow: a fill on the first plan raises the target, and a new order is sent for what is missing rather than the resting order being changed, so every broker order keeps the price it was given and its place in the queue. A target that shrinks cuts resting orders, newest first, as for any execution that does not change its order to grow. A rejected order stops it.
    """

    def needs_prices(self):
        """Whether this execution reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does not; it sends them when the target grows.

        Returns:
            bool: False.
        """
        return False

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing a resting order, which it is not; a new order is sent.

        Returns:
            bool: False.
        """
        return False

    def begin(self, plan_order, memory, quotes, now):
        """Readies the execution, which needs nothing.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): Unused.
            quotes (dict): Unused.
            now (float): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory, quotes, now

    def committed(self, pieces):
        """How much the orders sent so far account for: what filled of a finished one, and the whole of a resting one.

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

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now, sending_side=None):
        """One order for what the target is missing, when anything is.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): Unused.
            total (int): The quantity the order should trade in all.
            pieces (list): The broker orders sent so far.
            quotes (dict): Unused.
            now (float): Unused.
            sending_side (str | None): Unused.

        Returns:
            list: One quantity, or nothing.
        """
        del plan_order, quotes, now, sending_side
        missing = total - self.committed(pieces)
        if not self.will_send_more(memory, missing, pieces):
            return []
        return [
            missing,
        ]

    def will_send_more(self, memory, remaining, pieces):
        """Whether more may still be sent: while some is missing and the last order was not rejected.

        Args:
            memory (dict): Unused.
            remaining (int): The quantity missing.
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True when another order may follow.
        """
        del memory
        if pieces and pieces[-1].state == 'rejected':
            return False
        return remaining > 0

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            str: `top_up`.
        """
        return 'top_up'
