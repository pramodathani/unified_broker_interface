"""Shows that a `BrokerAssignment` stays on a thread until it is cleared, which is why a worker clears it after every parent.

A broker lane runs its parents on long-lived worker threads, one parent after another. The assignment belongs to the thread, not to the parent, so whatever one parent's run left in it is still there when the same thread picks up the next parent. `EnginePlacement.clear_assignment` resets it to None and an empty list, and the engine calls it when a worker finishes a parent, so the next parent's legs are chosen afresh.

The program runs three tasks on a thread pool with a single worker thread, so all three run on the same thread, in order. The first task assigns Zerodha and forgets to clear it; the second task, which was assigned nothing, finds Zerodha still there; it then clears the assignment, and the third task finds it empty. A fresh `BrokerAssignment` built for this program is used directly, the way `EnginePlacement` holds one, so nothing needs Redis, a broker or the network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_placement/BrokerAssignment/example_2_a_reused_thread_keeps_its_broker.py
"""

import concurrent.futures

from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    BrokerAssignment,
)


class AReusedThreadKeepsItsBrokerExample:
    """Runs three parents' worth of work on one pooled thread and shows what each finds in the assignment.

    Attributes:
        assignment (BrokerAssignment): The assignment the worker thread uses.
    """

    def __init__(self):
        """Builds the assignment.

        Returns:
            None: This method returns nothing.
        """
        self.assignment = BrokerAssignment()

    def first_parent(self):
        """Assigns Zerodha and leaves it in place.

        Returns:
            str: What the task found and did.
        """
        found = self.assignment.broker_name
        self.assignment.broker_name = 'zerodha'
        self.assignment.skipped = [
            {
                'broker': 'dhan',
                'reason': 'takes no SL-M orders',
            },
        ]
        return f'first parent found {found}, assigned zerodha and did not clear it'

    def second_parent(self):
        """Finds what the first parent left, then clears it as a worker should.

        Returns:
            str: What the task found and did.
        """
        found = self.assignment.broker_name
        found_skipped = self.assignment.skipped
        self.assignment.broker_name = None
        self.assignment.skipped = []
        return f'second parent found {found} with skipped {found_skipped}, then cleared it'

    def third_parent(self):
        """Finds the cleared assignment.

        Returns:
            str: What the task found.
        """
        return f'third parent found {self.assignment.broker_name} with skipped {self.assignment.skipped}'

    def run(self):
        """Runs the three tasks in order on one worker thread and prints what each found.

        Returns:
            None: This method returns nothing.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            tasks = [
                self.first_parent,
                self.second_parent,
                self.third_parent,
            ]
            for task in tasks:
                print(pool.submit(task).result())
        print(f'the main thread never had one: {self.assignment.broker_name}')


if __name__ == '__main__':
    AReusedThreadKeepsItsBrokerExample().run()
