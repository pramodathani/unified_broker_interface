"""Gives every open parent order that waits for a time its clock tick, on the calling thread.

Most synthetic order types wait for a fill, but a few wait for a time, such as a square-off at ten past three. Those types set `WANTS_CLOCK`, and the engine's loop asks a `ClockTicker` about once a second whether a tick is `due`, and then calls `tick`. The ticker reads every open parent, skips the ones whose type does not want the clock, and gives each of the rest a chance to act.

So that the output does not depend on the time of day, this program adds one small order type of its own to the registry of synthetic order types, `example_exit_at_time`, whose `on_clock_tick` acts when its parameters say it is due and raises when they name no time. A real type such as a time stop would compare the tick's time with its own, and would place orders through the engine's placement. The parent orders live in a small stand-in parent store, which holds five records: one parent that acts, one that is waiting, one that raises, one being cancelled, and one plain order that never wants the clock. A stand-in logger records the message the ticker writes for the parent that raises.

Notice that `due` compares a monotonic time you pass in with when the last tick ran, that only the due parent acts, and that the failing parent is logged without stopping the others.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/clock_ticker/ClockTicker/example_1_ticking_open_parents.py
"""

from unified_broker_interface.utilities.order_engine.base import (
    SyntheticOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.clock_ticker import (
    ClockTicker,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)


class ExitAtTime(SyntheticOrder):
    """A small order type that waits for a time, for this program only.

    Attributes:
        SYNTHETIC_TYPE (str): The name the registry knows it by.
        WANTS_CLOCK (bool): True, so the ticker gives it clock ticks.
    """

    SYNTHETIC_TYPE = 'example_exit_at_time'
    WANTS_CLOCK = True

    def on_clock_tick(self, now):
        """Acts when the parent's parameters say its time has come.

        Args:
            now (float): The time of the tick, in seconds since the epoch.

        Returns:
            bool: True when the parent acted.

        Raises:
            ValueError: When the parameters name no exit time.
        """
        if 'exit_at' not in self.parent.parameters:
            raise ValueError(f'No exit time: {self.parent.parent_order_id=}')
        if self.parent.parameters.get('is_due'):
            print(f'{self.parent.parent_order_id} exits its position at {self.parent.parameters["exit_at"]}')
            return True
        return False


class DictionaryParentStore:
    """A stand-in for the parent store that keeps parent records in a dictionary.

    Attributes:
        documents (dict): Each parent order id to its record.
    """

    def __init__(self, documents):
        """Builds the store.

        Args:
            documents (dict): Each parent order id to its record.

        Returns:
            None: This method returns nothing.
        """
        self.documents = documents

    def open_parent_ids(self):
        """The ids of the open parents, including one whose record has gone.

        Returns:
            list: The ids, sorted.
        """
        open_ids = list(self.documents)
        open_ids.append('parent-gone')
        return sorted(open_ids)

    def parent(self, parent_order_id):
        """One parent's record.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            dict | None: The record, or None when there is none.
        """
        return self.documents.get(parent_order_id)


class RecordingLogger:
    """A stand-in logger that keeps every message instead of writing it.

    Attributes:
        messages (list): The messages received, each prefixed with its level.
    """

    def __init__(self):
        """Builds the logger with no messages.

        Returns:
            None: This method returns nothing.
        """
        self.messages = []

    def exception(self, message):
        """Keeps an error message written while handling an exception.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(f'EXCEPTION {message}')


class TickingOpenParentsExample:
    """Ticks a set of open parents once and prints what happened.

    Attributes:
        logger (RecordingLogger): The stand-in logger.
        ticker (ClockTicker): The ticker being shown.
    """

    def __init__(self):
        """Adds the example type to the registry and builds the ticker over five parents.

        Returns:
            None: This method returns nothing.
        """
        SYNTHETIC_ORDER_CLASSES[ExitAtTime.SYNTHETIC_TYPE] = ExitAtTime
        documents = {
            'parent-1': self.document('parent-1', 'example_exit_at_time', 'working', True),
            'parent-2': self.document('parent-2', 'example_exit_at_time', 'working', False),
            'parent-3': self.document('parent-3', 'example_exit_at_time', 'working', None),
            'parent-4': self.document('parent-4', 'example_exit_at_time', 'cancelling', True),
            'parent-5': self.document('parent-5', 'simple', 'working', True),
        }
        self.logger = RecordingLogger()
        self.ticker = ClockTicker(
            DictionaryParentStore(documents),
            None,
            None,
            self.logger,
        )

    def document(self, parent_order_id, synthetic_type, state, is_due):
        """Builds one parent's record.

        Args:
            parent_order_id (str): The parent's id.
            synthetic_type (str): The order type.
            state (str): The parent's state.
            is_due (bool | None): Whether its time has come, or None to leave out the exit time.

        Returns:
            dict: The record.
        """
        parameters = {}
        if is_due is not None:
            parameters['exit_at'] = '15:10'
            parameters['is_due'] = is_due
        return {
            'parent_order_id': parent_order_id,
            'synthetic_type': synthetic_type,
            'state': state,
            'instrument_id': 'NSE:INFY',
            'parameters': parameters,
            'legs': [],
        }

    def run(self):
        """Checks whether a tick is due, ticks once and prints the counts.

        Returns:
            None: This method returns nothing.
        """
        timed = self.ticker.timed_types()
        print(f'example_exit_at_time wants the clock: {"example_exit_at_time" in timed}')
        print(f'simple wants the clock: {"simple" in timed}')
        print(f'Due half a second after the last tick: {self.ticker.due(self.ticker.ticked_at + 0.5)}')
        print(f'Due a second after the last tick: {self.ticker.due(self.ticker.ticked_at + 1.0)}')
        acted = self.ticker.tick()
        print(f'Parents that acted: {acted}')
        print(f'Ticks so far: {self.ticker.ticks}, acted in total: {self.ticker.acted}')
        for message in self.logger.messages:
            print(message)


if __name__ == '__main__':
    TickingOpenParentsExample().run()
