"""The worker threads that own the parent orders placed at one broker."""

import threading

from unified_broker_interface.utilities.order_engine.utilities.parent_worker import (
    ParentWorker,
)


class BrokerLane:
    """One broker's workers, which starts more of them when every one is busy.

    Each broker has a lane of its own, so a broker that answers slowly holds up only its own workers, and the number of workers a broker needs can be set for that broker. A new parent order goes to the least busy worker in its broker's lane. When every worker already has work, the lane starts one more, up to `maximum_workers`, because starting a thread takes about a twentieth of a millisecond and a waiting order costs a whole broker call.

    Workers are never stopped during the day. A worker usually owns parents that are still live, such as a bracket waiting for its entry to fill, and handing those to another worker part way through would mean two threads touching one parent.

    Attributes:
        broker_name (str): The broker, or a name for the lane of orders whose broker is not known yet.
        starting_workers (int): How many workers the lane starts with.
        maximum_workers (int): The most workers the lane grows to.
        logger (logging.Logger): The logger.
        workers (list): The lane's workers, in the order they were started.
        workers_lock (threading.Lock): Guards `workers`.
    """

    def __init__(self, broker_name, starting_workers, maximum_workers, logger):
        """Builds the lane with its starting workers, none of them started yet.

        Args:
            broker_name (str): The broker.
            starting_workers (int): How many workers to start with, at least one.
            maximum_workers (int): The most workers to grow to.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.starting_workers = max(1, starting_workers)
        self.maximum_workers = max(self.starting_workers, maximum_workers)
        self.logger = logger
        self.workers = []
        self.workers_lock = threading.Lock()
        for _ in range(self.starting_workers):
            self.workers.append(self.new_worker())

    def new_worker(self):
        """Builds the lane's next worker, not yet started.

        Returns:
            ParentWorker: The worker.
        """
        return ParentWorker(
            f'{self.broker_name}-{len(self.workers) + 1}',
            self.logger,
        )

    def start(self):
        """Starts every worker the lane has.

        Returns:
            None: This method returns nothing.
        """
        with self.workers_lock:
            for worker in self.workers:
                worker.start()

    def worker_for_new_parent(self):
        """The worker a new parent order should go to: the least busy one, or a new one when all are busy and the lane may grow.

        Returns:
            ParentWorker: The worker.
        """
        with self.workers_lock:
            chosen = self.workers[0]
            for worker in self.workers:
                if worker.current_load() < chosen.current_load():
                    chosen = worker
            if chosen.current_load() == 0:
                return chosen
            if len(self.workers) >= self.maximum_workers:
                return chosen
            worker = self.new_worker()
            worker.start()
            self.workers.append(worker)
        self.logger.info(
            f'Every {self.broker_name} worker was busy, so worker '
            f'{worker.name} was started.'
        )
        return worker

    def worker_count(self):
        """How many workers the lane has now.

        Returns:
            int: The count.
        """
        with self.workers_lock:
            return len(self.workers)

    def total_load(self):
        """How many pieces of work are waiting or running across the lane.

        Returns:
            int: The count.
        """
        with self.workers_lock:
            workers = list(self.workers)
        total = 0
        for worker in workers:
            total = total + worker.current_load()
        return total

    def stop(self, timeout_seconds):
        """Asks every worker to finish the work it has and stop, and waits for them.

        Args:
            timeout_seconds (float): The longest to wait for each worker.

        Returns:
            bool: True when every worker stopped in time.
        """
        with self.workers_lock:
            workers = list(self.workers)
        for worker in workers:
            worker.stop()
        stopped = True
        for worker in workers:
            if not worker.join(timeout_seconds):
                stopped = False
        return stopped
