"""Shows a rebuild that fails at 06:00 being left due, so the next pass of the engine's loop tries again.

If the event log cannot be read when the day rolls over, `roll` logs an error, returns -1 and does not mark the day as done. `due` therefore keeps answering True, and the engine calls `roll` again on its next pass. Marking the day done after a failure would leave every carried order silently not working until someone restarted the engine.

Three small stand-ins keep this offline. The recovery stand-in raises `ConnectionError` from its first `replay`, as a database that is still starting might, and returns one open parent from the second. The parent store is the real `ParentStore` with `rebuild` replaced by one that only counts parents, and the logger stand-in prints each message.

The program sets `last_reset` to 06:00 IST on 30 September 2026 after building the roll, and passes fixed moments to `due` and `roll`, so its output does not depend on today's date.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/day_roll/DayRoll/example_2_failed_rebuild_is_tried_again.py
"""

import datetime
import zoneinfo

from unified_broker_interface.utilities.order_engine.utilities.day_roll import (
    DayRoll,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class OpenParent:
    """A stand-in for a parent order that is still open.

    Attributes:
        parent_order_id (str): The parent's id.
    """

    def __init__(self, parent_order_id):
        """Builds the parent.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = parent_order_id

    def is_terminal(self):
        """Whether the parent has finished, which it has not.

        Returns:
            bool: Always False.
        """
        return False


class FlakyRecovery:
    """A stand-in for the engine's recovery whose first replay fails.

    Attributes:
        attempts (int): How many replays have been asked for.
    """

    def __init__(self):
        """Builds the stand-in with no attempts made.

        Returns:
            None: This method returns nothing.
        """
        self.attempts = 0

    def replay(self):
        """Fails the first time and returns one open parent afterwards.

        Returns:
            list: The parents.

        Raises:
            ConnectionError: On the first call.
        """
        self.attempts = self.attempts + 1
        if self.attempts == 1:
            raise ConnectionError('the database system is starting up')
        return [
            OpenParent('P-20260929-0012'),
        ]


class CountingParentStore(ParentStore):
    """The real parent store, with `rebuild` only counting the parents it is given.

    Attributes:
        rebuilt (int): How many parents the last rebuild was given.
    """

    def rebuild(self, parents):
        """Counts the parents the cache would be rebuilt with.

        Args:
            parents (list): The parents to write.

        Returns:
            None: This method returns nothing.
        """
        self.rebuilt = len(parents)


class PrintingLogger:
    """A stand-in for a logger that prints each message."""

    def info(self, message):
        """Prints an information message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'  INFO {message}')

    def error(self, message):
        """Prints an error message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'  ERROR {message}')


class FailedRebuildExample:
    """Rolls twice across one reset, the first time failing.

    Attributes:
        day_roll (DayRoll): The roll being shown.
    """

    def __init__(self):
        """Builds the roll as of 06:00 IST on 30 September 2026.

        Returns:
            None: This method returns nothing.
        """
        self.day_roll = DayRoll(FlakyRecovery(), CountingParentStore(None), PrintingLogger())
        self.day_roll.last_reset = datetime.datetime(2026, 9, 30, 6, 0, tzinfo=INDIA).timestamp()

    def run(self):
        """Prints each attempt's result and whether a roll is still due.

        Returns:
            None: This method returns nothing.
        """
        first_pass = datetime.datetime(2026, 10, 1, 6, 0, 1, tzinfo=INDIA)
        second_pass = datetime.datetime(2026, 10, 1, 6, 0, 2, tzinfo=INDIA)
        print(f'Due at {first_pass.isoformat()}: {self.day_roll.due(first_pass)}')
        print('First attempt:')
        print(f'  Result: {self.day_roll.roll(first_pass)}')
        print(f'Still due at {second_pass.isoformat()}: {self.day_roll.due(second_pass)}')
        print('Second attempt:')
        print(f'  Result: {self.day_roll.roll(second_pass)}')
        print(f'Due afterwards: {self.day_roll.due(second_pass)}')
        print(f'Rolls: {self.day_roll.rolls}')


if __name__ == '__main__':
    FailedRebuildExample().run()
