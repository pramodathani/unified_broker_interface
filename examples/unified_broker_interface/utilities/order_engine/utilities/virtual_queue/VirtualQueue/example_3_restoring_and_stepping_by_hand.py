"""Rebuilds a stored estimate after a restart and steps it by hand through a cancellation, a trade at the price and a trade through it.

The synthetic order book keeps each estimate in Redis as the dictionary `document` returns, and a restarted process rebuilds it with `VirtualQueue.from_document`. A rebuilt estimate always treats its next quote as a new baseline, because the quotes it missed cannot be told apart from trades. This program rebuilds one from a stored dictionary, takes a baseline, and then calls the three steps that `update` normally runs for each quote, one at a time, so each one's effect can be seen on its own.

It also shows that a document missing a field is refused with a ValueError, and that the constructor refuses a side other than BUY or SELL. No Redis is involved; the stored estimate is written out in the program.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/virtual_queue/VirtualQueue/example_3_restoring_and_stepping_by_hand.py
"""

from unified_broker_interface.utilities.order_engine.utilities.virtual_queue import (
    VirtualQueue,
)


class RestoringAndSteppingExample:
    """Rebuilds a stored buy estimate and moves it one step at a time.

    Attributes:
        stored (dict): The estimate as it was stored before the restart.
        quote (dict): The first quote seen after the restart.
    """

    def __init__(self):
        """Builds the stored estimate and the quote that follows the restart.

        Returns:
            None: This method returns nothing.
        """
        self.stored = {
            'parent_order_id': 'parent-3',
            'instrument_id': 'NFO:NIFTY25OCTFUT',
            'side': 'BUY',
            'price': '24810.5',
            'quantity': 150,
            'ahead': 600,
            'queue_filled': 0,
            'touched_at': None,
            'last_volume': 50000,
            'last_broker': 'fyers',
            'last_visible': 900,
            'updated_at': 1759215000.0,
            'updates': 42,
        }
        self.quote = {
            'broker': 'fyers',
            'volume': 51000,
            'last_price': 24811.0,
            'depth': {
                'buy': [
                    {
                        'price': 24810.5,
                        'quantity': 1000,
                    },
                ],
                'sell': [
                    {
                        'price': 24811.0,
                        'quantity': 450,
                    },
                ],
            },
        }

    def show(self, estimate, step):
        """Prints the estimate's place after one step.

        Args:
            estimate (VirtualQueue): The estimate.
            step (str): What was just done.

        Returns:
            None: This method returns nothing.
        """
        print(f'{step}: ahead={estimate.ahead} queue_filled={estimate.queue_filled} remaining={estimate.remaining()} needs_baseline={estimate.needs_baseline}')

    def run(self):
        """Rebuilds the estimate, steps it, and shows the two refusals.

        Returns:
            None: This method returns nothing.
        """
        estimate = VirtualQueue.from_document(self.stored)
        self.show(estimate, 'Rebuilt')
        estimate.take_baseline(self.quote, 51000)
        self.show(estimate, 'Baseline taken with 1000 visible')
        estimate.count_cancellations(0, 700)
        self.show(estimate, '300 left the level without trading')
        estimate.serve_queue(500)
        self.show(estimate, '500 traded at 24810.50')
        estimate.fill_through()
        self.show(estimate, 'A trade printed at 24810.00')
        print(f'Stored again: filled={estimate.document()["filled"]} updates={estimate.document()["updates"]}')
        broken = dict(self.stored)
        del broken['price']
        try:
            VirtualQueue.from_document(broken)
        except ValueError as error:
            print(f'Refused: {error}')
        try:
            VirtualQueue('parent-4', 'NSE:INFY', 'HOLD', '98', 10)
        except ValueError as error:
            print(f'Refused: {error}')


if __name__ == '__main__':
    RestoringAndSteppingExample().run()
