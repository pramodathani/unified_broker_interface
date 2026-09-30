"""Holds order updates that arrive before the engine knows their parent, and hands them back once it does.

A broker can report a fill over its websocket before the engine has finished reading the placement answer and saved the order id against its parent. The engine then has an update naming an order it does not recognise yet. It holds such updates in `EarlyUpdates`, keyed by `broker:order_id`, and after registering new orders asks `keys` which orders are waiting and `take` to collect the ones it now knows, in the order they arrived.

This program holds three updates for two Zerodha orders and one for a Dhan order, then pretends the engine has just registered the first Zerodha order. The update fields are shaped like entries on the `unified:order-updates` stream. The class needs no stand-ins, and nothing here waits long enough for the thirty-second expiry to matter.

Notice that `take` returns both updates for the registered order in arrival order, and the other two stay held.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/early_updates/EarlyUpdates/example_1_fill_before_the_order_id.py
"""

from unified_broker_interface.utilities.order_engine.utilities.early_updates import (
    EarlyUpdates,
)


class FillBeforeTheOrderIdExample:
    """Holds four early updates and takes the ones whose order becomes known.

    Attributes:
        early_updates (EarlyUpdates): The holding area being shown.
        arrivals (list): The updates to hold, as (key, fields) pairs in arrival order.
    """

    def __init__(self):
        """Builds the holding area and the updates that arrive early.

        Returns:
            None: This method returns nothing.
        """
        self.early_updates = EarlyUpdates()
        self.arrivals = [
            (
                'zerodha:250930000012345',
                {
                    'status': 'OPEN',
                    'filled_quantity': '0',
                },
            ),
            (
                'dhan:5225093012345',
                {
                    'status': 'OPEN',
                    'filled_quantity': '0',
                },
            ),
            (
                'zerodha:250930000012345',
                {
                    'status': 'COMPLETE',
                    'filled_quantity': '10',
                },
            ),
            (
                'zerodha:250930000012399',
                {
                    'status': 'REJECTED',
                    'filled_quantity': '0',
                },
            ),
        ]

    def run(self):
        """Prints the held keys before and after taking the updates for one known order.

        Returns:
            None: This method returns nothing.
        """
        for key, fields in self.arrivals:
            self.early_updates.hold(key, fields)
        print(f'Waiting orders: {self.early_updates.keys()}')
        self.early_updates.drop_expired()
        print(f'Still waiting after dropping expired ones: {self.early_updates.keys()}')
        known_keys = {
            'zerodha:250930000012345',
        }
        taken = self.early_updates.take(known_keys)
        print('Taken for zerodha:250930000012345:')
        for fields in taken:
            print(f'  {fields}')
        print(f'Waiting orders: {self.early_updates.keys()}')
        print(f'Dropped: {self.early_updates.dropped}')


if __name__ == '__main__':
    FillBeforeTheOrderIdExample().run()
