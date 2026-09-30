"""Shows a lane handing new parent orders to an idle worker instead of starting more workers.

The lane only grows when every worker it has is busy. This program builds a Dhan lane with two starting workers and room for four, starts it, and asks for a worker for five parent orders one after another, letting each piece of work finish before the next request. Every request finds an idle worker, so the lane never grows.

The lane also shows how its limits are cleaned up: a starting count below one becomes one, and a maximum below the starting count becomes the starting count. The program builds a second lane with a starting count of zero and a maximum of zero to show this, and never starts it.

Each piece of work only records which worker ran it, and the program waits for each worker's load to fall to zero before the next request, so the output does not depend on thread timing. It needs no broker, no data store and no network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/broker_lane/BrokerLane/example_2_idle_worker_is_reused.py
"""

import logging
import threading

from unified_broker_interface.utilities.order_engine.utilities.broker_lane import (
    BrokerLane,
)


class IdleWorkerIsReusedExample:
    """Hands out parent orders one at a time and prints which worker each went to.

    Attributes:
        lane (BrokerLane): The lane being shown.
        finished (threading.Event): Set by each piece of work when it has run.
    """

    def __init__(self):
        """Builds a Dhan lane with two starting workers and room for four.

        Returns:
            None: This method returns nothing.
        """
        self.lane = BrokerLane('dhan', 2, 4, logging.getLogger('example'))
        self.finished = threading.Event()

    def work(self, parent_id):
        """Pretends to place a parent order's first leg.

        Args:
            parent_id (str): The parent order.

        Returns:
            None: This method returns nothing.
        """
        self.finished.set()

    def wait_until_idle(self, worker):
        """Waits until a worker has nothing left to do.

        Args:
            worker (ParentWorker): The worker.

        Returns:
            None: This method returns nothing.
        """
        self.finished.wait(5.0)
        self.finished.clear()
        while worker.current_load() > 0:
            self.finished.wait(0.001)

    def run(self):
        """Hands out five parent orders, stops the lane and prints the results.

        Returns:
            None: This method returns nothing.
        """
        self.lane.start()
        for number in range(1, 6):
            parent_id = f'parent-{number}'
            worker = self.lane.worker_for_new_parent()
            print(f'{parent_id} goes to {worker.name}')
            worker.submit(
                self.work,
                (
                    parent_id,
                ),
            )
            self.wait_until_idle(worker)
        print(f'Workers after five orders: {self.lane.worker_count()}')
        print(f'Every worker stopped: {self.lane.stop(5.0)}')
        cleaned = BrokerLane('kotak', 0, 0, logging.getLogger('example'))
        print(f'A lane asked for 0 and at most 0 workers has {cleaned.starting_workers} and at most {cleaned.maximum_workers}')


if __name__ == '__main__':
    IdleWorkerIsReusedExample().run()
