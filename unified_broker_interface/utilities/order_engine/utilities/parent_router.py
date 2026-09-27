"""Which worker thread owns which parent order, and handing each piece of work to that worker."""

import threading
import time

from unified_broker_interface.utilities.order_engine.utilities.broker_lane import (
    BrokerLane,
)

UNASSIGNED_LANE = 'unassigned'
IDLE_POLL_SECONDS = 0.01


class ParentRouter:
    """Keeps one lane of workers per broker and remembers which worker owns each parent order.

    The engine's main thread reads the streams and the clock, and hands each piece of work here. A new intent goes to the least busy worker in the lane of the broker chosen for it. Everything after that about the same parent, whether a fill, a clock tick or a price tick, goes to the worker that took its intent, so one parent is only ever touched by one thread.

    A parent this process has not seen yet, such as one recovered at start, is given to a worker the first time any work for it arrives, in the lane of the broker its legs went to. A parent whose broker is not known, because the choice could not be made or nothing has been placed yet, goes to a lane of its own, `unassigned`.

    Attributes:
        lanes (dict): Each broker's name to its `BrokerLane`, plus the `unassigned` lane.
        logger (logging.Logger): The logger.
        owners (dict): Each parent order id to the `ParentWorker` that owns it.
        owners_lock (threading.Lock): Guards `owners`.
    """

    def __init__(self, broker_names, starting_workers, maximum_workers, logger):
        """Builds one lane per broker and one for parents whose broker is not known, none of them started yet.

        Args:
            broker_names (list): Every broker's name.
            starting_workers (dict): Each broker's name to how many workers its lane starts with; a broker left out starts with one.
            maximum_workers (int): The most workers any lane grows to.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logger
        self.lanes = {}
        for broker_name in broker_names:
            self.lanes[broker_name] = BrokerLane(
                broker_name,
                starting_workers.get(broker_name, 1),
                maximum_workers,
                logger,
            )
        self.lanes[UNASSIGNED_LANE] = BrokerLane(
            UNASSIGNED_LANE,
            1,
            maximum_workers,
            logger,
        )
        self.owners = {}
        self.owners_lock = threading.Lock()

    @staticmethod
    def starting_workers_from_text(text, broker_names):
        """Reads how many workers each broker's lane starts with, from a default and per-broker overrides.

        The text is a number, optionally followed by `broker=number` overrides, all separated by commas: `10` or `10,zerodha=6,dhan=12`.

        Args:
            text (str): The configured text.
            broker_names (list): Every broker's name.

        Returns:
            dict: Each broker's name to its starting worker count.

        Raises:
            ValueError: When a part is not a whole number of at least one, or an override names no broker, so a misspelt setting stops the engine rather than running it with a lane of the wrong size.
        """
        default_count = 1
        overrides = {}
        for part in text.replace(' ', '').split(','):
            if not part:
                continue
            if '=' in part:
                broker_name, count_text = part.split('=', 1)
                if broker_name not in broker_names:
                    raise ValueError(
                        f'the worker count {part!r} names no broker; brokers are {", ".join(broker_names)}'
                    )
                overrides[broker_name] = ParentRouter.whole_count(count_text, part)
            else:
                default_count = ParentRouter.whole_count(part, part)
        counts = {}
        for broker_name in broker_names:
            counts[broker_name] = overrides.get(broker_name, default_count)
        return counts

    @staticmethod
    def whole_count(count_text, part):
        """Reads one worker count, which must be a whole number of at least one.

        Args:
            count_text (str): The number as written.
            part (str): The whole part of the setting it came from, for the message.

        Returns:
            int: The count.

        Raises:
            ValueError: When the number is not a whole number of at least one.
        """
        try:
            count = int(count_text)
        except ValueError:
            raise ValueError(f'the worker count {part!r} is not a whole number')
        if count < 1:
            raise ValueError(f'the worker count {part!r} is below one')
        return count

    def start(self):
        """Starts every lane's workers.

        Returns:
            None: This method returns nothing.
        """
        for lane in self.lanes.values():
            lane.start()

    def lane_for(self, broker_name):
        """The lane for a broker, or the unassigned lane when the broker is not known.

        Args:
            broker_name (str | None): The broker.

        Returns:
            BrokerLane: The lane.
        """
        if broker_name in self.lanes:
            return self.lanes[broker_name]
        return self.lanes[UNASSIGNED_LANE]

    def worker_for_new_intent(self, broker_name):
        """The worker that will place a new intent, from the lane of the broker chosen for it.

        Args:
            broker_name (str | None): The broker chosen for the intent, or None when none could be chosen.

        Returns:
            ParentWorker: The worker.
        """
        return self.lane_for(broker_name).worker_for_new_parent()

    def register(self, parent_order_id, worker):
        """Records that a worker owns a parent, so every later piece of work about it goes there.

        Args:
            parent_order_id (str): The parent's id.
            worker (ParentWorker): The worker.

        Returns:
            None: This method returns nothing.
        """
        with self.owners_lock:
            self.owners[parent_order_id] = worker

    def owner(self, parent_order_id, broker_name):
        """The worker that owns a parent, giving it one first when this process has not seen it before.

        Args:
            parent_order_id (str): The parent's id.
            broker_name (str | None): The broker the parent's legs went to, used only when it has no owner yet.

        Returns:
            ParentWorker: The worker.
        """
        with self.owners_lock:
            worker = self.owners.get(parent_order_id)
            if worker is not None:
                return worker
            worker = self.lane_for(broker_name).worker_for_new_parent()
            self.owners[parent_order_id] = worker
            return worker

    @staticmethod
    def broker_of_document(document):
        """The broker a stored parent's legs went to, for choosing a lane.

        Args:
            document (dict): The parent's Redis record.

        Returns:
            str | None: The first leg's broker, or None when no leg has one.
        """
        for leg in document.get('legs') or []:
            if isinstance(leg, dict) and leg.get('broker'):
                return leg.get('broker')
        return None

    def route(self, parent_order_id, broker_name, function, arguments):
        """Hands one piece of work about a parent to the worker that owns it.

        Args:
            parent_order_id (str): The parent's id.
            broker_name (str | None): The broker the parent's legs went to, used only when it has no owner yet.
            function (callable): What to run.
            arguments (tuple): Its arguments.

        Returns:
            None: This method returns nothing.
        """
        worker = self.owner(parent_order_id, broker_name)
        worker.submit(function, arguments)

    def total_load(self):
        """How many pieces of work are waiting or running across every lane.

        Returns:
            int: The count.
        """
        total = 0
        for lane in self.lanes.values():
            total = total + lane.total_load()
        return total

    def wait_until_idle(self, stop, timeout_seconds):
        """Waits until no worker has any work, or time runs out, or the engine is stopping.

        The day roll rebuilds every parent's cache from the record, which must not happen while a worker is changing a parent.

        Args:
            stop (threading.Event): Set when the engine is stopping.
            timeout_seconds (float): The longest to wait.

        Returns:
            bool: True when every worker was idle.
        """
        deadline = time.monotonic() + timeout_seconds
        while self.total_load() > 0:
            if stop.is_set() or time.monotonic() >= deadline:
                return False
            time.sleep(IDLE_POLL_SECONDS)
        return True

    def forget_owners(self):
        """Forgets every parent's owner, once every worker is idle at the day roll.

        Parents still open are given an owner again the first time work for them arrives.

        Returns:
            None: This method returns nothing.
        """
        with self.owners_lock:
            self.owners = {}

    def worker_counts(self):
        """How many workers each lane has, for the shutdown line.

        Returns:
            dict: Each lane's name to its worker count.
        """
        counts = {}
        for lane_name, lane in self.lanes.items():
            counts[lane_name] = lane.worker_count()
        return counts

    def stop(self, timeout_seconds):
        """Asks every worker to finish the work it has and stop.

        Args:
            timeout_seconds (float): The longest to wait for each worker.

        Returns:
            bool: True when every worker stopped in time.
        """
        stopped = True
        for lane in self.lanes.values():
            if not lane.stop(timeout_seconds):
                stopped = False
        return stopped
