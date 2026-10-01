"""The execution that shows only part of an order at a time."""

import zlib


class IcebergExecution:
    """A plan order's execution that shows `visible_quantity` at a time and sends the next piece only once the last one has filled.

    It keeps the rules of today's iceberg type. A piece may be varied by up to `randomise_percent` either way, worked out from the parent's id and how many pieces have gone, so the size is the same every time it is worked out but does not repeat a pattern another trader could spot. If a piece is cancelled or rejected rather than filled, no more pieces are sent, because whoever stopped it meant the order to stop.

    Attributes:
        visible_quantity (int): The size of each piece before any variation.
        randomise_percent (int): How far a piece may vary either way, as a percentage.
    """

    def __init__(self, visible_quantity, randomise_percent):
        """Builds the execution from settings the plan reader has already checked.

        Args:
            visible_quantity (int): The size of each piece.
            randomise_percent (int): How far a piece may vary, from 0 up to 99.

        Returns:
            None: This method returns nothing.
        """
        self.visible_quantity = visible_quantity
        self.randomise_percent = randomise_percent

    def needs_prices(self):
        """Whether this execution reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does not; it sends them when the last one fills.

        Returns:
            bool: False.
        """
        return False

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing the resting order, which it is not; more pieces are sent instead.

        Returns:
            bool: False.
        """
        return False

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

    def piece_size(self, plan_order, pieces):
        """The size of the next piece before it is capped at what is left.

        Args:
            plan_order (PlanOrder): The plan order, whose parent id seeds the variation.
            pieces (list): The broker orders sent so far.

        Returns:
            int: The size, at least one.
        """
        wanted = self.visible_quantity
        if self.randomise_percent > 0:
            seed = zlib.crc32(f'{plan_order.parent.parent_order_id}:{len(pieces)}'.encode())
            spread = wanted * self.randomise_percent / 100
            offset = (seed % 2001) / 1000 - 1
            wanted = int(round(wanted + spread * offset))
        return max(wanted, 1)

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now, sending_side=None):
        """The next piece, when nothing is resting and the last piece filled.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): Unused.
            total (int): The quantity the order should trade in all.
            pieces (list): The broker orders sent so far, as legs.
            quotes (dict): Unused.
            now (float): Unused.
            sending_side (str | None): Unused.

        Returns:
            list: One quantity, or nothing.
        """
        del memory, quotes, now, sending_side
        if not self.will_send_more({}, total - self.committed(pieces), pieces):
            return []
        for piece in pieces:
            if not piece.is_finished():
                return []
        remaining = total - self.committed(pieces)
        return [
            min(self.piece_size(plan_order, pieces), remaining),
        ]

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

    def will_send_more(self, memory, remaining, pieces):
        """Whether more pieces may still be sent: while some is left and the last piece, if any, filled.

        Args:
            memory (dict): Unused.
            remaining (int): The quantity not yet sent.
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True when another piece may follow.
        """
        del memory
        if remaining < 1:
            return False
        if not pieces:
            return True
        last = pieces[-1]
        return not last.is_finished() or last.state == 'filled'

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'iceberg': {
                'visible_quantity': self.visible_quantity,
                'randomise_percent': self.randomise_percent,
            },
        }
