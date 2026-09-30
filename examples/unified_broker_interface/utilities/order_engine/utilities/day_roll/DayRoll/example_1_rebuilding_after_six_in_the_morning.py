"""Notices that the engine has crossed 06:00 IST and rebuilds the parent caches from the record.

The engine's Redis copies of its parent orders expire at the next 06:00 IST. A stop order carried across days would vanish from them while the engine kept running, so on every pass of its loop the engine asks `DayRoll.due` whether a reset has passed since it last looked, and if so calls `roll`, which replays the event log through the recovery object and writes the result back with `ParentStore.rebuild`.

Three small stand-ins keep this offline. The recovery stand-in returns two ready-made parents from `replay`, one still open (a stop carried from Monday) and one finished. The parent store is the real `ParentStore`, so `reset_epochs` works out the 06:00 boundaries exactly as in production, but its `rebuild` is replaced so it prints what it would write instead of sending it to Redis. The logger stand-in prints each message.

`DayRoll` takes the reset that has already passed when it is built as accounted for, which depends on today's date. The program sets `last_reset` to 06:00 IST on 30 September 2026 right after building it, and passes fixed moments to `due` and `roll`, so the output is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/day_roll/DayRoll/example_1_rebuilding_after_six_in_the_morning.py
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


class RecordedParent:
    """A stand-in for a parent order rebuilt from the record.

    Attributes:
        parent_order_id (str): The parent's id.
        state (str): The parent's state.
    """

    def __init__(self, parent_order_id, state):
        """Builds the parent.

        Args:
            parent_order_id (str): The parent's id.
            state (str): The parent's state.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = parent_order_id
        self.state = state

    def is_terminal(self):
        """Whether the parent has finished.

        Returns:
            bool: True when the state is final.
        """
        return self.state in (
            'filled',
            'cancelled',
            'rejected',
        )


class ReplayingRecovery:
    """A stand-in for the engine's recovery that returns fixed parents.

    Attributes:
        parents (list): The parents `replay` returns.
    """

    def __init__(self, parents):
        """Builds the stand-in.

        Args:
            parents (list): The parents `replay` returns.

        Returns:
            None: This method returns nothing.
        """
        self.parents = parents

    def replay(self):
        """Returns the parents as if rebuilt from the event log.

        Returns:
            list: The parents.
        """
        return self.parents


class PrintingParentStore(ParentStore):
    """The real parent store, with `rebuild` printing what it would write instead of writing it."""

    def rebuild(self, parents):
        """Prints each parent the cache would be rebuilt with.

        Args:
            parents (list): The parents to write.

        Returns:
            None: This method returns nothing.
        """
        for parent in parents:
            print(f'  Rebuilding {parent.parent_order_id} ({parent.state})')


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


class RebuildingAfterSixExample:
    """Asks the roll whether it is due at three moments and rolls once.

    Attributes:
        day_roll (DayRoll): The roll being shown.
    """

    def __init__(self):
        """Builds the roll over two recorded parents, as of 06:00 IST on 30 September 2026.

        Returns:
            None: This method returns nothing.
        """
        parents = [
            RecordedParent('P-20260928-0007', 'armed'),
            RecordedParent('P-20260930-0031', 'filled'),
        ]
        store = PrintingParentStore(None)
        self.day_roll = DayRoll(ReplayingRecovery(parents), store, PrintingLogger())
        self.day_roll.last_reset = datetime.datetime(2026, 9, 30, 6, 0, tzinfo=INDIA).timestamp()

    def run(self):
        """Prints whether a roll is due before and after 06:00 on 1 October, and rolls.

        Returns:
            None: This method returns nothing.
        """
        late_evening = datetime.datetime(2026, 9, 30, 23, 15, tzinfo=INDIA)
        next_morning = datetime.datetime(2026, 10, 1, 6, 0, 5, tzinfo=INDIA)
        print(f'Due at {late_evening.isoformat()}: {self.day_roll.due(late_evening)}')
        print(f'Due at {next_morning.isoformat()}: {self.day_roll.due(next_morning)}')
        print('Rolling:')
        still_open = self.day_roll.roll(next_morning)
        print(f'Parents still open: {still_open}')
        print(f'Due again at {next_morning.isoformat()}: {self.day_roll.due(next_morning)}')
        print(f'Rolls so far: {self.day_roll.rolls}')


if __name__ == '__main__':
    RebuildingAfterSixExample().run()
