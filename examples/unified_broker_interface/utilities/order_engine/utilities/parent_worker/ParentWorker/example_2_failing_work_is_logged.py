"""Shows that a worker logs a piece of work that raises and carries on with the next one.

One parent order's failure must not stop every other parent the same worker owns. This program hands a worker three pieces of work for three parent orders, and the middle one raises a `ValueError`. The worker catches it, logs it with `logger.exception`, and runs the third piece as usual.

To keep the output independent of thread timing, the program never starts the worker's thread. It queues the work, queues the stop marker with `stop`, and then calls `run` itself, which empties the inbox on the calling thread and returns at the stop marker. That is exactly what the thread would have done. A small stand-in logger records the messages it is given instead of printing a traceback, so the output shows only the message the worker wrote.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_worker/ParentWorker/example_2_failing_work_is_logged.py
"""

from unified_broker_interface.utilities.order_engine.utilities.parent_worker import (
    ParentWorker,
)


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

    def info(self, message):
        """Keeps an information message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(f'INFO {message}')

    def exception(self, message):
        """Keeps an error message written while handling an exception.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(f'EXCEPTION {message}')


class FailingWorkIsLoggedExample:
    """Runs three pieces of work, one of which raises, and prints what the worker did.

    Attributes:
        logger (RecordingLogger): The stand-in logger.
        worker (ParentWorker): The worker being shown.
        done (list): The parent orders whose work finished.
    """

    def __init__(self):
        """Builds a worker named after the second Dhan worker.

        Returns:
            None: This method returns nothing.
        """
        self.logger = RecordingLogger()
        self.worker = ParentWorker('dhan-2', self.logger)
        self.done = []

    def place(self, parent_id):
        """Pretends to place a parent order's first leg.

        Args:
            parent_id (str): The parent order.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the parent order is `parent-2`, which has no price.
        """
        if parent_id == 'parent-2':
            raise ValueError(f'No price for the order: {parent_id=}')
        self.done.append(parent_id)

    def run(self):
        """Queues the work and the stop marker, empties the inbox and prints the results.

        Returns:
            None: This method returns nothing.
        """
        parent_ids = [
            'parent-1',
            'parent-2',
            'parent-3',
        ]
        for parent_id in parent_ids:
            self.worker.submit(
                self.place,
                (
                    parent_id,
                ),
            )
        self.worker.stop()
        print(f'Load before running: {self.worker.current_load()}')
        self.worker.run()
        print(f'Load after running: {self.worker.current_load()}')
        print(f'Finished: {self.done}')
        for message in self.logger.messages:
            print(message)


if __name__ == '__main__':
    FailingWorkIsLoggedExample().run()
