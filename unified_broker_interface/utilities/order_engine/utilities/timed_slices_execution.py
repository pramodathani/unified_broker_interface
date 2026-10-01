"""What every execution that sends slices on a clock has in common."""


class TimedSlicesExecution:
    """A plan order's execution that cuts the quantity into `slices` and sends one every `over_minutes × 60 / slices` seconds, the first at once.

    It keeps the schedule of today's TWAP type, which VWAP and implementation shortfall share. The quantity is shared out by weight with the largest-remainder method: each slice gets the whole part of its share, and the units left over go to the slices whose fractions were biggest, earliest first, so equal weights give exactly an even split. Each slice's size is worked out from the order's total when the slice is due, so a total a join grows or shrinks is spread over the slices still to come; the last slice sends whatever is left. A slice that has not filled is left resting when the next goes, as today.

    A subclass says only how the slices are weighted, in `slice_weights`.

    Attributes:
        slices (int): How many slices, from 2 up to 60.
        over_minutes (float): The minutes the slices are spread across.
    """

    NAME = 'timed_slices'

    def __init__(self, slices, over_minutes):
        """Builds the execution from settings the plan reader has already checked.

        Args:
            slices (int): How many slices.
            over_minutes (float): The minutes to spread them across.

        Returns:
            None: This method returns nothing.
        """
        self.slices = slices
        self.over_minutes = over_minutes

    def needs_prices(self):
        """Whether this execution reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does, when each slice falls due.

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

    def interval(self):
        """The seconds between one slice and the next.

        Returns:
            float: The interval.
        """
        return self.over_minutes * 60 / self.slices

    def begin(self, plan_order, memory, quotes, now):
        """Starts the clock.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): The execution's memory, given `started_at`.
            quotes (dict): Unused.
            now (float): The Unix time the order started working.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, quotes
        memory['started_at'] = now

    def slice_weights(self, memory):
        """The relative share of the order each slice takes.

        Args:
            memory (dict): The execution's memory, which holds when the schedule started.

        Returns:
            list: One weight per slice.

        Raises:
            NotImplementedError: Always, because each timed execution weights its slices differently.
        """
        raise NotImplementedError(
            f'{type(self).__name__} must say how its slices are weighted.'
        )

    def slice_quantities(self, total, memory):
        """Each slice's quantity, sharing `total` out by weight with the largest-remainder method.

        Args:
            total (int): The quantity to share out.
            memory (dict): The execution's memory.

        Returns:
            list: One quantity per slice, adding up to `total`.
        """
        weights = self.slice_weights(memory)
        total_weight = sum(weights)
        if total_weight <= 0:
            weights = [1.0] * self.slices
            total_weight = float(self.slices)
        exact = []
        quantities = []
        for weight in weights:
            share = total * weight / total_weight
            exact.append(share)
            quantities.append(int(share))
        left_over = total - sum(quantities)
        fractions = []
        for index in range(self.slices):
            fractions.append((-(exact[index] - quantities[index]), index))
        fractions.sort()
        for position in range(left_over):
            quantities[fractions[position % self.slices][1]] += 1
        return quantities

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now):
        """The next slice, once its time has come.

        One slice is sent per tick at most, as today, so a tick that arrives late sends the slice that is due and the next tick catches up. Which slice is next is read from how many broker orders this order has placed, which recovery rebuilds after a restart; only the start time is kept in memory.

        Args:
            plan_order (PlanOrder): Unused.
            memory (dict): The execution's memory, holding `started_at`.
            total (int): The quantity the order should trade in all.
            pieces (list): The broker orders sent so far, as legs.
            quotes (dict): Unused.
            now (float): The Unix time of the tick.

        Returns:
            list: One quantity, or nothing.
        """
        del plan_order, quotes
        index = len(pieces)
        started_at = memory.get('started_at')
        if started_at is None or index >= self.slices:
            return []
        if now < started_at + self.interval() * index:
            return []
        sent = 0
        for piece in pieces:
            sent = sent + (piece.quantity or 0)
        remaining = total - sent
        if index == self.slices - 1:
            quantity = remaining
        else:
            quantity = min(self.slice_quantities(total, memory)[index], remaining)
        if quantity < 1:
            return []
        return [
            quantity,
        ]

    def will_send_more(self, memory, remaining, pieces):
        """Whether more slices may still be sent: while some are left on the schedule and some quantity is left.

        Args:
            memory (dict): Unused.
            remaining (int): The quantity not yet sent.
            pieces (list): The broker orders sent so far, one per slice.

        Returns:
            bool: True when another slice may follow.
        """
        del memory
        return remaining > 0 and len(pieces) < self.slices

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            self.NAME: {
                'slices': self.slices,
                'over_minutes': self.over_minutes,
            },
        }
