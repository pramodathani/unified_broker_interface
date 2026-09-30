"""Shows that one `BrokerAssignment` holds a separate broker for every thread that uses it.

The order engine runs parents on worker threads, several at once, and each worker may be running a parent that intake assigned to a different broker. `EnginePlacement` keeps a single `BrokerAssignment` for all of them. Because the class is a `threading.local`, each thread that touches it gets its own `broker_name` and `skipped`, starting from None and an empty list, and never sees another thread's.

The program shares one assignment between the main thread and two worker threads. Each worker writes its own broker and the brokers intake passed over, waits at a barrier until the other worker has written too, and then reads its values back. Both read back what they wrote, and the main thread still reads the values it set, so no thread overwrote another's. The workers report through a dictionary keyed by broker name, so the output does not depend on which thread finishes first.

Nothing here needs Redis, a broker or the network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_placement/BrokerAssignment/example_1_one_broker_per_thread.py
"""

import threading

from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    BrokerAssignment,
)


class OneBrokerPerThreadExample:
    """Writes different brokers into one shared assignment from two threads and reads each back.

    Attributes:
        assignment (BrokerAssignment): The assignment every thread shares.
        barrier (threading.Barrier): Makes both workers write before either reads.
        read_back (dict): Each worker's broker to what that worker read back.
        lock (threading.Lock): Guards `read_back`.
    """

    def __init__(self):
        """Builds the shared assignment and the barrier.

        Returns:
            None: This method returns nothing.
        """
        self.assignment = BrokerAssignment()
        self.barrier = threading.Barrier(2)
        self.read_back = {}
        self.lock = threading.Lock()

    def work(self, broker_name, skipped):
        """Runs on a worker thread: reads the fresh values, writes its own, waits and reads them back.

        Args:
            broker_name (str): The broker this worker's parent was assigned.
            skipped (list): The brokers intake passed over for that parent.

        Returns:
            None: This method returns nothing.
        """
        fresh = (
            self.assignment.broker_name,
            list(self.assignment.skipped),
        )
        self.assignment.broker_name = broker_name
        self.assignment.skipped = skipped
        self.barrier.wait()
        with self.lock:
            self.read_back[broker_name] = {
                'fresh': fresh,
                'broker_name': self.assignment.broker_name,
                'skipped': self.assignment.skipped,
            }

    def run(self):
        """Sets the main thread's values, runs both workers and prints what every thread read.

        Returns:
            None: This method returns nothing.
        """
        self.assignment.broker_name = 'fyers'
        workers = [
            threading.Thread(
                target=self.work,
                args=(
                    'zerodha',
                    [],
                ),
            ),
            threading.Thread(
                target=self.work,
                args=(
                    'dhan',
                    [
                        {
                            'broker': 'zerodha',
                            'reason': 'has no login in Redis',
                        },
                    ],
                ),
            ),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        for broker_name in sorted(self.read_back):
            values = self.read_back[broker_name]
            print(f'worker for {broker_name}: started with {values["fresh"]}, read back {values["broker_name"]} and skipped {values["skipped"]}')
        print(f'main thread still reads: {self.assignment.broker_name} and skipped {self.assignment.skipped}')


if __name__ == '__main__':
    OneBrokerPerThreadExample().run()
