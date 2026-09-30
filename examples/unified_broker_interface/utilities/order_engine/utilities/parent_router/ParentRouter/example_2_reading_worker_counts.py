"""Reads how many workers each broker's lane starts with from the configured text, and shows the settings it refuses.

The order engine's worker setting is a default number, optionally followed by `broker=number` overrides, such as `2,zerodha=4`. `ParentRouter.starting_workers_from_text` turns it into one count per broker, and `ParentRouter.whole_count` checks each number. A number that is not whole, a number below one, or an override that names no broker raises `ValueError`, so a misspelt setting stops the engine instead of running it with a lane of the wrong size.

This program reads one good setting, builds a router from it and prints each lane's worker count without starting any thread, then tries three bad settings and prints each error message. It needs no broker, no data store and no network.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/parent_router/ParentRouter/example_2_reading_worker_counts.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.parent_router import (
    ParentRouter,
)


class ReadingWorkerCountsExample:
    """Reads good and bad worker settings and prints what the router makes of them.

    Attributes:
        broker_names (list): The brokers the engine runs.
    """

    def __init__(self):
        """Names the three brokers the program pretends the engine runs.

        Returns:
            None: This method returns nothing.
        """
        self.broker_names = [
            'zerodha',
            'dhan',
            'fyers',
        ]

    def run(self):
        """Prints the counts from a good setting and the errors from bad ones.

        Returns:
            None: This method returns nothing.
        """
        counts = ParentRouter.starting_workers_from_text(' 2, zerodha=4 ', self.broker_names)
        print(f'Counts from "2, zerodha=4": {counts}')
        router = ParentRouter(self.broker_names, counts, 6, logging.getLogger('example'))
        print(f'Workers per lane: {router.worker_counts()}')
        print(f'The count "3" reads as {ParentRouter.whole_count("3", "dhan=3")}')
        bad_settings = [
            '2,upstox=3',
            'two',
            '2,dhan=0',
        ]
        for text in bad_settings:
            try:
                ParentRouter.starting_workers_from_text(text, self.broker_names)
            except ValueError as error:
                print(f'"{text}" is refused: {error}')


if __name__ == '__main__':
    ReadingWorkerCountsExample().run()
