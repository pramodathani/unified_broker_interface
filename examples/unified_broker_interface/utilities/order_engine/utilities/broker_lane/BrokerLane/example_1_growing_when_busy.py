"""Shows a broker's lane of workers starting one more worker when every worker it has is busy.

A `BrokerLane` holds the worker threads for one broker. A new parent order goes to the least busy worker, and when every worker already has work the lane starts another, up to `maximum_workers`. This program builds a Zerodha lane that starts with one worker and may grow to two, and asks it for a worker three times while the first piece of work is still running.

To make the output independent of thread timing, the first piece of work waits on a `threading.Event` that the program sets only at the end, so the first worker is certainly busy while the lane chooses. Each piece of work only records which worker ran it, so the program needs no broker, no data store and no network. The standard `logging` module is the logger; the lane logs at info level when it grows, which is not shown because the default level is warning.

Notice that the second request starts `zerodha-2`, and the third returns the less busy of the two workers because the lane has reached its maximum. After `stop`, the lane's total load is zero.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/broker_lane/BrokerLane/example_1_growing_when_busy.py
"""

import logging
import threading

from unified_broker_interface.utilities.order_engine.utilities.broker_lane import (
    BrokerLane,
)


class GrowingWhenBusyExample:
    """Asks a lane for workers while its only worker is busy, and prints what it chose.

    Attributes:
        lane (BrokerLane): The lane being shown.
        release (threading.Event): Set to let the first piece of work finish.
        started (threading.Event): Set once the first piece of work is running.
        ran (list): The pieces of work that ran, as `parent on worker` lines.
        ran_lock (threading.Lock): Guards `ran`.
    """

    def __init__(self):
        """Builds a Zerodha lane with one starting worker and room for two.

        Returns:
            None: This method returns nothing.
        """
        self.lane = BrokerLane('zerodha', 1, 2, logging.getLogger('example'))
        self.release = threading.Event()
        self.started = threading.Event()
        self.ran = []
        self.ran_lock = threading.Lock()

    def slow_work(self, parent_id, worker_name):
        """Pretends to wait for a slow broker until the program releases it.

        Args:
            parent_id (str): The parent order.
            worker_name (str): The worker running it.

        Returns:
            None: This method returns nothing.
        """
        self.started.set()
        self.release.wait(5.0)
        with self.ran_lock:
            self.ran.append(f'{parent_id} on {worker_name}')

    def quick_work(self, parent_id, worker_name):
        """Pretends to place an order at once.

        Args:
            parent_id (str): The parent order.
            worker_name (str): The worker running it.

        Returns:
            None: This method returns nothing.
        """
        with self.ran_lock:
            self.ran.append(f'{parent_id} on {worker_name}')

    def run(self):
        """Hands out three parent orders, releases the slow one, stops the lane and prints the results.

        Returns:
            None: This method returns nothing.
        """
        self.lane.start()
        print(f'Workers at the start: {self.lane.worker_count()}')
        first = self.lane.worker_for_new_parent()
        print(f'parent-1 goes to {first.name}')
        first.submit(
            self.slow_work,
            (
                'parent-1',
                first.name,
            ),
        )
        self.started.wait(5.0)
        second = self.lane.worker_for_new_parent()
        print(f'parent-2 goes to {second.name}')
        print(f'Workers now: {self.lane.worker_count()}')
        print(f'Load across the lane: {self.lane.total_load()}')
        third = self.lane.worker_for_new_parent()
        print(f'parent-3 goes to {third.name}, since the lane is at its maximum of {self.lane.maximum_workers}')
        spare = self.lane.new_worker()
        print(f'The next worker would be named {spare.name}')
        self.release.set()
        second.submit(
            self.quick_work,
            (
                'parent-2',
                second.name,
            ),
        )
        stopped = self.lane.stop(5.0)
        print(f'Every worker stopped: {stopped}')
        print(f'Load after stopping: {self.lane.total_load()}')
        for line in sorted(self.ran):
            print(line)


if __name__ == '__main__':
    GrowingWhenBusyExample().run()
