"""Routes every piece of work about a parent order to the one worker that owns it.

A `ParentRouter` keeps one lane of workers per broker, plus an `unassigned` lane for parents whose broker is not known. A new intent goes to a worker in the lane of the broker chosen for it, the router records that worker as the parent's owner, and every later piece of work about that parent goes to the same worker.

This program builds a router for Zerodha and Dhan, takes a worker for a new Zerodha intent and registers it, and then routes a fill and a clock tick to that parent. It also routes work for a parent recovered at start, which has no owner yet, so the router finds its broker from the stored record with `broker_of_document` and picks a worker in that lane. A parent whose record names no broker goes to the `unassigned` lane.

Each piece of work only records which worker ran it. The program waits with `wait_until_idle` before printing, so the output does not depend on thread timing, and it needs no broker, no data store and no network. At the end it forgets every owner, as the day roll does, and stops every worker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_router/ParentRouter/example_1_routing_work_to_owners.py
"""

import logging
import threading

from unified_broker_interface.utilities.order_engine.utilities.parent_router import (
    ParentRouter,
)


class RoutingWorkToOwnersExample:
    """Routes work for three parent orders and prints which worker ran each piece.

    Attributes:
        router (ParentRouter): The router being shown.
        ran (list): Lines saying which worker ran which piece of work.
        ran_lock (threading.Lock): Guards `ran`.
    """

    def __init__(self):
        """Builds a router for Zerodha and Dhan, with two Zerodha workers and one Dhan worker.

        Returns:
            None: This method returns nothing.
        """
        broker_names = [
            'zerodha',
            'dhan',
        ]
        starting_workers = {
            'zerodha': 2,
        }
        self.router = ParentRouter(
            broker_names,
            starting_workers,
            4,
            logging.getLogger('example'),
        )
        self.ran = []
        self.ran_lock = threading.Lock()

    def work(self, parent_order_id, step):
        """Records one piece of work and the thread that ran it.

        Args:
            parent_order_id (str): The parent order.
            step (str): What the work does.

        Returns:
            None: This method returns nothing.
        """
        with self.ran_lock:
            self.ran.append(f'{parent_order_id} {step} on {threading.current_thread().name}')

    def run(self):
        """Routes the work, waits for it, prints the results and stops the router.

        Returns:
            None: This method returns nothing.
        """
        self.router.start()
        print(f'Workers per lane: {self.router.worker_counts()}')
        worker = self.router.worker_for_new_intent('zerodha')
        self.router.register('parent-1', worker)
        print(f'parent-1 is owned by {self.router.owner("parent-1", None).name}')
        self.router.route(
            'parent-1',
            'zerodha',
            self.work,
            (
                'parent-1',
                'fill',
            ),
        )
        self.router.route(
            'parent-1',
            None,
            self.work,
            (
                'parent-1',
                'clock tick',
            ),
        )
        recovered = {
            'parent_order_id': 'parent-2',
            'legs': [
                {
                    'leg_id': 'leg-1',
                    'broker': 'dhan',
                },
            ],
        }
        recovered_broker = ParentRouter.broker_of_document(recovered)
        print(f'parent-2 was recovered with legs at {recovered_broker}, so its lane is {self.router.lane_for(recovered_broker).broker_name}')
        self.router.route(
            'parent-2',
            recovered_broker,
            self.work,
            (
                'parent-2',
                'price tick',
            ),
        )
        unplaced = {
            'parent_order_id': 'parent-3',
            'legs': [],
        }
        unplaced_broker = ParentRouter.broker_of_document(unplaced)
        print(f'parent-3 has no broker ({unplaced_broker}), so its lane is {self.router.lane_for(unplaced_broker).broker_name}')
        self.router.route(
            'parent-3',
            unplaced_broker,
            self.work,
            (
                'parent-3',
                'expiry',
            ),
        )
        idle = self.router.wait_until_idle(threading.Event(), 5.0)
        print(f'Every worker idle: {idle}')
        print(f'Load across every lane: {self.router.total_load()}')
        for line in sorted(self.ran):
            print(line)
        self.router.forget_owners()
        print(f'Owners after the day roll: {len(self.router.owners)}')
        print(f'Every worker stopped: {self.router.stop(5.0)}')


if __name__ == '__main__':
    RoutingWorkToOwnersExample().run()
