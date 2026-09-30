"""Hands each parent's clock tick to the worker thread that owns it, and never queues a second tick while the first is waiting.

In the running engine a `ClockTicker` is given the engine's `ParentRouter`, so `tick` does not run a parent itself. It hands the parent to the worker that owns it with `hand_over`, and the worker later calls `run_handed_over`, which reads the parent afresh and gives it the tick. If a worker is stuck on a slow broker call, the parent's next tick is not queued behind the first, because the ticker remembers which parents have a tick pending.

This program shows that with a real router for Zerodha. The worker that owns the parent is first given a piece of work that waits on a `threading.Event`, standing in for a slow broker call, so the tick is certainly still pending when the program ticks a second time. Only after that does the program release the worker and wait until every worker is idle, so the output does not depend on thread timing. It also calls `hand_over`, `run_handed_over` and `run_one` directly to show what each does on its own.

As in the first example, a small order type of the program's own, `example_countdown`, is added to the registry so the output does not depend on the time of day; it counts its ticks and acts on each. The parent records live in a small stand-in parent store, and the program needs no broker, no data store and no network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/clock_ticker/ClockTicker/example_2_ticks_handed_to_workers.py
"""

import logging
import threading

from unified_broker_interface.utilities.order_engine.base import (
    SyntheticOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.clock_ticker import (
    ClockTicker,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_router import (
    ParentRouter,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)


class Countdown(SyntheticOrder):
    """A small order type that acts on every clock tick, for this program only.

    Attributes:
        SYNTHETIC_TYPE (str): The name the registry knows it by.
        WANTS_CLOCK (bool): True, so the ticker gives it clock ticks.
        TICKS_SEEN (list): The parents ticked, in order, on whichever thread ran them.
    """

    SYNTHETIC_TYPE = 'example_countdown'
    WANTS_CLOCK = True
    TICKS_SEEN = []

    def on_clock_tick(self, now):
        """Records the tick and acts.

        Args:
            now (float): The time of the tick, in seconds since the epoch.

        Returns:
            bool: Always True.
        """
        Countdown.TICKS_SEEN.append(f'{self.parent.parent_order_id} on {threading.current_thread().name}')
        return True


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
        """The ids of the open parents.

        Returns:
            list: The ids, sorted.
        """
        return sorted(self.documents)

    def parent(self, parent_order_id):
        """One parent's record.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            dict | None: The record, or None when there is none.
        """
        return self.documents.get(parent_order_id)


class TicksHandedToWorkersExample:
    """Ticks one parent twice through a router while its worker is busy, and prints what ran.

    Attributes:
        document (dict): The one parent's record.
        router (ParentRouter): The router that owns the worker threads.
        ticker (ClockTicker): The ticker being shown.
        release (threading.Event): Set to let the slow piece of work finish.
        started (threading.Event): Set once the slow piece of work is running.
    """

    def __init__(self):
        """Adds the example type to the registry and builds a router and a ticker over one Zerodha parent.

        Returns:
            None: This method returns nothing.
        """
        SYNTHETIC_ORDER_CLASSES[Countdown.SYNTHETIC_TYPE] = Countdown
        self.document = {
            'parent_order_id': 'parent-1',
            'synthetic_type': 'example_countdown',
            'state': 'working',
            'instrument_id': 'NSE:INFY',
            'parameters': {},
            'legs': [
                {
                    'leg_id': 'leg-1',
                    'broker': 'zerodha',
                },
            ],
        }
        documents = {
            'parent-1': self.document,
        }
        broker_names = [
            'zerodha',
        ]
        logger = logging.getLogger('example')
        self.router = ParentRouter(broker_names, {}, 1, logger)
        self.ticker = ClockTicker(
            DictionaryParentStore(documents),
            None,
            None,
            logger,
            None,
            self.router,
        )
        self.release = threading.Event()
        self.started = threading.Event()

    def slow_broker_call(self):
        """Pretends to wait for a slow broker until the program releases it.

        Returns:
            None: This method returns nothing.
        """
        self.started.set()
        self.release.wait(5.0)

    def run(self):
        """Ticks twice while the worker is busy, releases it and prints the results.

        Returns:
            None: This method returns nothing.
        """
        self.router.start()
        self.router.route('parent-1', 'zerodha', self.slow_broker_call, ())
        self.started.wait(5.0)
        self.ticker.tick()
        print(f'Pending after the first tick: {sorted(self.ticker.pending)}')
        self.ticker.tick()
        self.ticker.hand_over('parent-1', self.document)
        print(f'Work waiting on the worker after two more tries: {self.router.total_load()}')
        self.release.set()
        self.router.wait_until_idle(threading.Event(), 5.0)
        print(f'Pending once the worker is free: {sorted(self.ticker.pending)}')
        print(f'Ticks: {self.ticker.ticks}, acted in total: {self.ticker.acted}')
        self.ticker.run_handed_over('parent-1')
        print(f'Acted in total after running a handed-over tick here: {self.ticker.acted}')
        print(f'run_one on a copy of the record acts: {self.ticker.run_one(dict(self.document))}')
        for line in Countdown.TICKS_SEEN:
            print(line)
        print(f'Every worker stopped: {self.router.stop(5.0)}')


if __name__ == '__main__':
    TicksHandedToWorkersExample().run()
