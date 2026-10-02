"""An execution nested inside another: the outer one splits the order into slices, and the inner one works each slice."""

OUTER_NAMES = (
    'twap',
    'vwap',
    'front_loaded',
    'participation',
    'iceberg',
)
INNER_NAMES = (
    'iceberg',
    'twap',
    'vwap',
    'front_loaded',
)


class SlicePiece:
    """One slice the outer execution has released, as the outer execution sees it: its size, what its broker orders have filled, whether it has finished, and its state, the four things executions read from a broker order.

    Attributes:
        quantity (int): The slice's size.
        filled_quantity (int): What its broker orders have filled.
        finished (bool): Whether nothing more of it will fill.
        state (str): `filled`, `rejected` when every broker order was refused, `cancelled` when it finished otherwise, or `working`.
    """

    def __init__(self, quantity, filled_quantity, finished, state):
        """Builds the slice.

        Args:
            quantity (int): The slice's size.
            filled_quantity (int): What its broker orders have filled.
            finished (bool): Whether nothing more of it will fill.
            state (str): `filled`, `rejected`, `cancelled` or `working`.

        Returns:
            None: This method returns nothing.
        """
        self.quantity = quantity
        self.filled_quantity = filled_quantity
        self.finished = finished
        self.state = state

    def is_finished(self):
        """Whether nothing more of this slice will fill.

        Returns:
            bool: True once its inner execution sends nothing more and every one of its broker orders has finished.
        """
        return self.finished


class NestedExecution:
    """A plan order's execution of two values, in list order: the outer one splits the whole quantity into slices as it would its pieces, and the inner one works each slice as it would a whole order, such as TWAP slices each shown as an iceberg.

    Neither execution changes. The outer one is shown the slices it has released, as `SlicePiece`s, in place of broker orders; each slice's inner execution is shown that slice's own broker orders. Which slice each broker order belongs to is kept in memory as `leg_slices`, one slice number per broker order in the order they were sent, since `OrderPart.send_due` places the pieces it is given in order and places all of them or none. A slice's inner memory is kept beside it, and recorded with the order, so a restart repeats nothing.

    Attributes:
        outer (object): The execution that splits the order into slices.
        inner (object): The execution that works each slice.
    """

    def __init__(self, outer, inner):
        """Builds the execution from two the plan reader has already checked.

        Args:
            outer (object): The outer execution.
            inner (object): The inner execution.

        Returns:
            None: This method returns nothing.
        """
        self.outer = outer
        self.inner = inner

    def needs_prices(self):
        """Whether either execution reads quotes.

        Returns:
            bool: True when one does.
        """
        return self.outer.needs_prices() or self.inner.needs_prices()

    def paced_by_ticks(self):
        """Whether pieces may fall due on later ticks, which they do when either execution is paced.

        Returns:
            bool: True when either is paced by ticks.
        """
        return self.outer.paced_by_ticks() or self.inner.paced_by_ticks()

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing a resting order, which it is not; more slices are sent instead.

        Returns:
            bool: False.
        """
        return False

    def begin(self, plan_order, memory, quotes, now):
        """Starts the outer execution's clock or count, with no slice released yet.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): The execution's memory, changed in place.
            quotes (dict): The quotes now.
            now (float): The Unix time now.

        Returns:
            None: This method returns nothing.
        """
        memory['outer'] = {}
        memory['slices'] = []
        memory['leg_slices'] = []
        self.outer.begin(plan_order, memory['outer'], quotes, now)

    def slice_legs(self, memory, pieces, index):
        """The broker orders sent for one slice.

        Args:
            memory (dict): The execution's memory.
            pieces (list): The order's broker orders, in the order they were sent.
            index (int): The slice's number.

        Returns:
            list: The legs.
        """
        found = []
        leg_slices = memory.get('leg_slices') or []
        for position, piece in enumerate(pieces):
            if position < len(leg_slices) and leg_slices[position] == index:
                found.append(piece)
        return found

    def slice_pieces(self, memory, pieces):
        """Every slice released so far, as the outer execution sees it.

        Args:
            memory (dict): The execution's memory.
            pieces (list): The order's broker orders.

        Returns:
            list: One `SlicePiece` per slice.
        """
        released = []
        for index, slice_record in enumerate(memory.get('slices') or []):
            legs = self.slice_legs(memory, pieces, index)
            filled = 0
            all_finished = True
            all_rejected = bool(legs)
            sent = 0
            for leg in legs:
                filled = filled + (leg.filled_quantity or 0)
                if leg.state != 'rejected':
                    all_rejected = False
                if leg.is_finished():
                    sent = sent + (leg.filled_quantity or 0)
                else:
                    sent = sent + (leg.quantity or 0)
                    all_finished = False
            remaining = slice_record['quantity'] - sent
            finished = all_finished and not self.inner.will_send_more(slice_record.get('inner') or {}, remaining, legs)
            if not finished:
                state = 'working'
            elif filled >= slice_record['quantity']:
                state = 'filled'
            elif all_rejected:
                state = 'rejected'
            else:
                state = 'cancelled'
            released.append(SlicePiece(slice_record['quantity'], filled, finished, state))
        return released

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now, sending_side=None):
        """The broker orders to send now: the inner execution's pieces for every slice, new slices included.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): The execution's memory, changed in place.
            total (int): The order's quantity.
            pieces (list): The order's broker orders, in the order they were sent.
            quotes (dict): The quotes now.
            now (float): The Unix time now.
            sending_side (str | None): BUY or SELL.

        Returns:
            list: One quantity per broker order to send.
        """
        memory.setdefault('outer', {})
        memory.setdefault('slices', [])
        memory.setdefault('leg_slices', [])
        released = self.slice_pieces(memory, pieces)
        new_slices = self.outer.due_pieces(plan_order, memory['outer'], total, released, quotes, now, sending_side=sending_side)
        for quantity in new_slices:
            inner_memory = {}
            self.inner.begin(plan_order, inner_memory, quotes, now)
            memory['slices'].append({
                'quantity': quantity,
                'inner': inner_memory,
            })
        due = []
        for index, slice_record in enumerate(memory['slices']):
            legs = self.slice_legs(memory, pieces, index)
            inner_memory = slice_record.get('inner') or {}
            quantities = self.inner.due_pieces(plan_order, inner_memory, slice_record['quantity'], legs, quotes, now, sending_side=sending_side)
            slice_record['inner'] = inner_memory
            for quantity in quantities:
                due.append(quantity)
                memory['leg_slices'].append(index)
        return due

    def will_send_more(self, memory, remaining, pieces):
        """Whether more will be sent: a slice the outer execution has still to release, or more of a slice already released.

        The outer execution is asked with what it has not yet released as slices: the order's quantity, which is what remains plus what the broker orders account for, less what the slices hold.

        Args:
            memory (dict): The execution's memory.
            remaining (int): The order's quantity not yet accounted for by its broker orders.
            pieces (list): The order's broker orders.

        Returns:
            bool: True when more will be sent.
        """
        released = self.slice_pieces(memory, pieces)
        released_total = 0
        for slice_piece in released:
            released_total = released_total + slice_piece.quantity
        committed = 0
        for piece in pieces:
            if piece.is_finished():
                committed = committed + (piece.filled_quantity or 0)
            else:
                committed = committed + (piece.quantity or 0)
        not_released = remaining + committed - released_total
        if self.outer.will_send_more(memory.get('outer') or {}, not_released, released):
            return True
        for slice_piece in released:
            if not slice_piece.is_finished():
                return True
        return False

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The outer and inner executions, in order.
        """
        return {
            'nested': [
                self.outer.described(),
                self.inner.described(),
            ],
        }
