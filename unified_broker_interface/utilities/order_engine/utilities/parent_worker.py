"""One worker thread, which does every piece of work for the parent orders it owns, one piece at a time."""

import queue
import threading

STOP = None


class ParentWorker:
    """A thread with an inbox, which runs the work handed to it in the order it arrived.

    Every piece of work about one parent order goes to the one worker that owns it: the intent that creates it, the broker's updates about its legs, and its clock and price ticks. A parent is therefore only ever touched by one thread, so the order types need no locks, and each type's code still reads top to bottom with a broker call that blocks until it is answered.

    A piece of work is a function and its arguments. A function that raises is logged and the worker carries on, because one parent's failure must not stop every other parent this worker owns.

    Attributes:
        name (str): The thread's name, such as `zerodha-3`.
        logger (logging.Logger): The logger.
        inbox (queue.Queue): The work not yet started, each a `(function, arguments)` pair, or `STOP`.
        load_lock (threading.Lock): Guards `load`.
        load (int): How many pieces of work are waiting or running.
        thread (threading.Thread): The thread.
    """

    def __init__(self, name, logger):
        """Builds a worker that has not started.

        Args:
            name (str): The thread's name.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.name = name
        self.logger = logger
        self.inbox = queue.Queue()
        self.load_lock = threading.Lock()
        self.load = 0
        self.thread = threading.Thread(
            target=self.run,
            name=f'order-engine-{name}',
            daemon=True,
        )

    def start(self):
        """Starts the thread.

        Returns:
            None: This method returns nothing.
        """
        self.thread.start()

    def submit(self, function, arguments):
        """Hands the worker one piece of work, to run after everything already handed to it.

        Args:
            function (callable): What to run.
            arguments (tuple): Its arguments.

        Returns:
            None: This method returns nothing.
        """
        with self.load_lock:
            self.load = self.load + 1
        self.inbox.put((function, arguments))

    def current_load(self):
        """How many pieces of work are waiting or running.

        Returns:
            int: The count.
        """
        with self.load_lock:
            return self.load

    def run(self):
        """Runs work until told to stop.

        Returns:
            None: This method returns nothing.
        """
        while True:
            item = self.inbox.get()
            if item is STOP:
                return
            function, arguments = item
            try:
                function(*arguments)
            except Exception:
                self.logger.exception(
                    f'Order engine worker {self.name} failed on a piece of '
                    'work, and carries on with the next.'
                )
            finally:
                with self.load_lock:
                    self.load = self.load - 1

    def stop(self):
        """Asks the thread to stop once the work handed to it before this call is done.

        Returns:
            None: This method returns nothing.
        """
        self.inbox.put(STOP)

    def join(self, timeout_seconds):
        """Waits for the thread to stop.

        Args:
            timeout_seconds (float): The longest to wait.

        Returns:
            bool: True when the thread has stopped.
        """
        self.thread.join(timeout_seconds)
        return not self.thread.is_alive()
