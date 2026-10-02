"""The execution that trades a fixed share of the volume the market itself trades."""


class ParticipationExecution:
    """A plan order's execution that, on each tick, sends `percent` of the volume traded since its last slice, until the order is sent or `most_slices` have gone.

    It keeps the rules of today's participation type. The volume is the day's cumulative `volume` in the instrument's live quote, and the count starts from the volume when the order starts working, so nothing traded before then counts. A share of less than one unit waits for more volume. A slice that rests unfilled still counts as sent, as today; the unfilled part of a slice that is cancelled is sent again by later slices, and a slice the broker rejects stops the order rather than inviting a fresh rejection on every tick.

    Attributes:
        percent (float): The share of traded volume to send, above zero and at most 100.
        most_slices (int): The most slices it will send.
    """

    def __init__(self, percent, most_slices):
        """Builds the execution from settings the plan reader has already checked.

        Args:
            percent (float): The share of traded volume to send.
            most_slices (int): The most slices it will send.

        Returns:
            None: This method returns nothing.
        """
        self.percent = percent
        self.most_slices = most_slices

    def needs_prices(self):
        """Whether this execution reads quotes, which it does, for the traded volume.

        Returns:
            bool: True.
        """
        return True

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does, as volume trades.

        Returns:
            bool: True.
        """
        return True

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing a resting order, which it is not; later slices grow instead.

        Returns:
            bool: False.
        """
        return False

    def volume_of(self, plan_order, quotes):
        """The day's traded volume in the order's instrument, from the live quote.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which names its instrument.
            quotes (dict): The quotes, by instrument id.

        Returns:
            int | None: The volume, or None when the quote does not carry it.
        """
        quote = (quotes or {}).get(plan_order.instrument_id)
        if not isinstance(quote, dict):
            return None
        value = quote.get('volume')
        if isinstance(value, bool):
            return None
        try:
            volume = int(value)
        except (TypeError, ValueError):
            return None
        if volume < 0:
            return None
        return volume

    def begin(self, plan_order, memory, quotes, now):
        """Starts counting from the volume traded so far.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The execution's memory, given `counted_volume`.
            quotes (dict): The quotes the order started working on.
            now (float): Unused.

        Returns:
            None: This method returns nothing.
        """
        del now
        memory['counted_volume'] = self.volume_of(plan_order, quotes)

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
        """The next slice: the share of the volume traded since the last one, when it comes to a whole unit.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The execution's memory, whose `counted_volume` moves on when a slice is due.
            total (int): The quantity the order should trade in all.
            pieces (list): The broker orders sent so far, one per slice.
            quotes (dict): The quotes the tick carried.
            now (float): Unused.
            sending_side (str | None): Unused.

        Returns:
            list: One quantity, or nothing.
        """
        del now, sending_side
        remaining = total - self.committed(pieces)
        if not self.will_send_more(memory, remaining, pieces):
            return []
        volume = self.volume_of(plan_order, quotes)
        counted = memory.get('counted_volume')
        if volume is None:
            return []
        if counted is None:
            memory['counted_volume'] = volume
            return []
        traded = volume - counted
        share = min(int(traded * self.percent / 100), remaining)
        lot = self.lot_size(plan_order)
        share = share - share % lot
        if share < 1:
            return []
        memory['counted_volume'] = volume
        return [
            share,
        ]

    def lot_size(self, plan_order):
        """The order's instrument's lot at the broker the plan's orders go to, which every slice must be a whole number of.

        A share of the market's volume rarely comes to whole lots, and a slice that does not is refused when it is sent. So it is cut down to whole lots, and a share under one lot leaves `counted_volume` where it was, so the volume goes on counting towards the next slice.

        Args:
            plan_order (OrderContext): The order's view of the plan order.

        Returns:
            int: The lot, at least one: the chosen broker's, or before any broker is chosen the largest any broker lists.
        """
        instrument, _, _ = plan_order.placement.market_context(plan_order.instrument_id, False, False)
        handles = instrument.handles or {}
        broker_name = plan_order.chosen_broker()
        if broker_name is not None:
            chosen = {
                broker_name: handles.get(broker_name) or {},
            }
            handles = chosen
        largest = 1
        for handle in handles.values():
            try:
                size = int(float(handle.get('lot_size') or 1))
            except (TypeError, ValueError):
                size = 1
            largest = max(largest, size)
        return largest

    def will_send_more(self, memory, remaining, pieces):
        """Whether more slices may still be sent: while some is left and fewer than `most_slices` have gone.

        Args:
            memory (dict): Unused.
            remaining (int): The quantity not yet sent.
            pieces (list): The broker orders sent so far, one per slice.

        Returns:
            bool: True when another slice may follow.
        """
        del memory
        if self.last_was_rejected(pieces):
            return False
        return remaining > 0 and len(pieces) < self.most_slices

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'participation': {
                'percent': self.percent,
                'most_slices': self.most_slices,
            },
        }
