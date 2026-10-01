"""The execution that sends an order's whole quantity as one broker order."""


class AllAtOnceExecution:
    """A plan order's execution that sends the whole quantity at once, as one broker order.

    It is the default, and what every order did before the Execution slot existed. When a join changes how much the order should trade, its one resting order is changed rather than another being sent, so a bracket's exits grow and shrink in place.
    """

    def needs_prices(self):
        """Whether this execution reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does not.

        Returns:
            bool: False.
        """
        return False

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing the resting order rather than sending another, which it is.

        Returns:
            bool: True.
        """
        return True

    def begin(self, plan_order, memory, quotes, now):
        """Readies the execution when the order starts working, which needs nothing.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): Unused.
            quotes (dict): Unused.
            now (float): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory, quotes, now

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now):
        """The pieces to send now: everything, while nothing has been sent.

        Whether the order has gone is read from its broker orders, which recovery rebuilds after a restart, rather than from memory, so a restarted engine never sends it twice.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): Unused.
            total (int): The quantity the order should trade in all.
            pieces (list): The broker orders sent so far, as legs.
            quotes (dict): Unused.
            now (float): Unused.

        Returns:
            list: One quantity, or nothing once the order has been sent.
        """
        del plan_order, memory, quotes, now
        if pieces or total < 1:
            return []
        return [
            total,
        ]

    def will_send_more(self, memory, remaining, pieces):
        """Whether more pieces may still be sent, which they may not once the order has gone.

        Args:
            memory (dict): Unused.
            remaining (int): Unused.
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True only before the order has been sent.
        """
        del memory, remaining
        return not pieces

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            str: `all_at_once`.
        """
        return 'all_at_once'
