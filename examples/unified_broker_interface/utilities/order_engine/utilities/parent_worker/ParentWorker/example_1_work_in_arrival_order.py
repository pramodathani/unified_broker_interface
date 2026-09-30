"""Hands a worker three pieces of work for one parent order and shows they run one at a time, in the order they arrived.

A `ParentWorker` is a thread with an inbox. The order engine gives every piece of work about one parent order to the same worker, so the parent is only ever touched by one thread. This program hands the worker three pieces of work before starting it, which shows `current_load` counting work that is waiting, and then starts the thread, asks it to stop once the inbox is empty, and waits for it.

Each piece of work only appends a line to a list, so the program needs no broker, no data store and no network. The standard `logging` module is used as the logger, and nothing is logged because no piece of work fails. Notice that the lines come out in the order they were submitted and that the load falls back to zero once the thread has stopped.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_worker/ParentWorker/example_1_work_in_arrival_order.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.parent_worker import (
    ParentWorker,
)


class WorkInArrivalOrderExample:
    """Runs three pieces of work on one worker and prints what happened.

    Attributes:
        worker (ParentWorker): The worker being shown.
        done (list): The lines written by the pieces of work, in the order they ran.
    """

    def __init__(self):
        """Builds a worker named after the first Zerodha worker.

        Returns:
            None: This method returns nothing.
        """
        self.worker = ParentWorker('zerodha-1', logging.getLogger('example'))
        self.done = []

    def note(self, parent_id, step):
        """Records one piece of work about a parent order.

        Args:
            parent_id (str): The parent order the work is about.
            step (str): What the work does.

        Returns:
            None: This method returns nothing.
        """
        self.done.append(f'{parent_id}: {step}')

    def run(self):
        """Submits the work, starts the worker, stops it and prints the results.

        Returns:
            None: This method returns nothing.
        """
        self.worker.submit(
            self.note,
            (
                'parent-7',
                'place the entry leg',
            ),
        )
        self.worker.submit(
            self.note,
            (
                'parent-7',
                'apply the broker update',
            ),
        )
        self.worker.submit(
            self.note,
            (
                'parent-7',
                'check the clock tick',
            ),
        )
        print(f'Worker: {self.worker.name}')
        print(f'Load before starting: {self.worker.current_load()}')
        self.worker.start()
        self.worker.stop()
        stopped = self.worker.join(5.0)
        print(f'Stopped in time: {stopped}')
        print(f'Load after stopping: {self.worker.current_load()}')
        for line in self.done:
            print(line)


if __name__ == '__main__':
    WorkInArrivalOrderExample().run()
