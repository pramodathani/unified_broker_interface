"""Shows held updates being dropped when they wait too long or when too many are held.

An update that still names no known order after the holding time belongs to an order this engine never placed, such as one placed by hand in the broker's own app, so `drop_expired` discards it. And the holding area has a ceiling, so a flood of unknown updates cannot grow memory without limit; past `maximum_held`, the oldest are dropped as new ones arrive. Both kinds of drop are counted in `dropped`.

The real holding time is thirty seconds. To keep the program short, it builds the holding area with a holding time of 0.2 seconds and a ceiling of three, and waits 0.3 seconds with `time.sleep`. The timing only decides which side of the cut-off each update falls, and the gap is wide enough that the output is the same on every run. No stand-ins are needed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/early_updates/EarlyUpdates/example_2_dropping_old_and_excess_updates.py
"""

import time

from unified_broker_interface.utilities.order_engine.utilities.early_updates import (
    EarlyUpdates,
)


class DroppingOldAndExcessUpdatesExample:
    """Overfills a small holding area, then lets some of its updates expire.

    Attributes:
        early_updates (EarlyUpdates): A holding area with a 0.2 second holding time and room for three.
    """

    def __init__(self):
        """Builds the small holding area.

        Returns:
            None: This method returns nothing.
        """
        self.early_updates = EarlyUpdates(hold_seconds=0.2, maximum_held=3)

    def run(self):
        """Prints the held keys and the dropped count after each step.

        Returns:
            None: This method returns nothing.
        """
        order_keys = [
            'fyers:23093000001',
            'fyers:23093000002',
            'fyers:23093000003',
            'fyers:23093000004',
        ]
        for key in order_keys:
            self.early_updates.hold(
                key,
                {
                    'status': 'OPEN',
                },
            )
        print(f'After holding four with room for three: {self.early_updates.keys()}')
        print(f'  Dropped: {self.early_updates.dropped}')
        time.sleep(0.3)
        self.early_updates.hold(
            'kotak:250930000000777',
            {
                'status': 'COMPLETE',
            },
        )
        self.early_updates.drop_expired()
        print(f'After 0.3 seconds and one fresh update: {self.early_updates.keys()}')
        print(f'  Dropped: {self.early_updates.dropped}')
        taken = self.early_updates.take({
            'fyers:23093000004',
        })
        print(f'Taking fyers:23093000004, which expired: {taken}')


if __name__ == '__main__':
    DroppingOldAndExcessUpdatesExample().run()
