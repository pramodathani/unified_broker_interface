"""How often one resting order may be moved, which is what keeps a chasing type honest."""

import time


class RepricingThrottle:
    """Refuses to move a resting order again too soon after the last move.

    A type that follows the market has no natural limit of its own. A chaser told to sit on the best bid will move its order every time the bid moves, and on a liquid instrument the bid moves several times a second all day. Left alone, one such order can spend an entire account's request allowance and push the order-to-trade ratio somewhere an exchange will ask about.

    This is the second half of that limit, and it is deliberately separate from the rate budget. The budget asks whether the system as a whole may send another request; this asks whether this particular order has been moved recently enough that another move is churn. An account well inside its budget can still be moving one order thirty times a second, and only this catches that.

    The memory is kept per leg, in this process, and is not written down. Exactly one engine runs, so there is nowhere else for it to be, and after a restart the first move of every leg is allowed at once, which is the right answer: a leg whose price nobody has touched since the engine came back should be brought to where it belongs without waiting.

    Attributes:
        minimum_seconds (float): The shortest gap allowed between two moves of one leg.
        moved_at (dict): The monotonic time each leg was last moved at, by leg id.
        suppressed (int): How many moves were refused for being too soon.
        allowed (int): How many moves were allowed.
    """

    def __init__(self, minimum_seconds):
        """Builds the throttle.

        Args:
            minimum_seconds (float): The shortest gap allowed between two moves of one leg, where zero turns the throttle off.

        Returns:
            None: This method returns nothing.
        """
        self.minimum_seconds = minimum_seconds
        self.moved_at = {}
        self.suppressed = 0
        self.allowed = 0

    def allows(self, leg_id, now=None):
        """Whether this leg may be moved now, counting the answer either way.

        Args:
            leg_id (str): The leg being moved.
            now (float | None): The monotonic time, or None for now.

        Returns:
            bool: True when the move may be sent.
        """
        if self.minimum_seconds <= 0:
            self.allowed = self.allowed + 1
            return True
        now = now if now is not None else time.monotonic()
        last = self.moved_at.get(leg_id)
        if last is not None and (now - last) < self.minimum_seconds:
            self.suppressed = self.suppressed + 1
            return False
        self.allowed = self.allowed + 1
        return True

    def record(self, leg_id, now=None):
        """Remembers that this leg has just been moved.

        This is called after the broker accepted the change rather than before it was sent. A move the broker refused did not move anything, and making the type wait before trying again would leave an order sitting at a price the market has left.

        Args:
            leg_id (str): The leg that moved.
            now (float | None): The monotonic time, or None for now.

        Returns:
            None: This method returns nothing.
        """
        self.moved_at[leg_id] = now if now is not None else time.monotonic()

    def forget(self, leg_id):
        """Drops a finished leg's memory, so the map does not grow all day.

        Args:
            leg_id (str): The leg that has finished.

        Returns:
            None: This method returns nothing.
        """
        self.moved_at.pop(leg_id, None)

    def counts(self):
        """What the throttle has done, for the engine's closing log line.

        Returns:
            dict: The allowed and suppressed counts and the gap in force.
        """
        return {
            'minimum_seconds': self.minimum_seconds,
            'allowed': self.allowed,
            'suppressed': self.suppressed,
        }
