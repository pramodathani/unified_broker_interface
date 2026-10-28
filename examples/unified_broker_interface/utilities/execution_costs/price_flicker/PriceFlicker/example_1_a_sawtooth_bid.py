"""Measures the flicker of a bid that dips 0.20 every other second and comes straight back.

A `PriceFlicker` takes the price a stop watches, the bid for a bought position, and measures for each tick how far it fell within the next few seconds. The percentile of those moves is the wobble a stop must stand beyond so as not to be fired by it. This program builds a minute of ticks by hand, so it needs no database.

Notice that half the moves are zero, because the low ticks only ever go back up, and that the 90th percentile is the full 0.20 dip.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/price_flicker/PriceFlicker/example_1_a_sawtooth_bid.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.price_flicker import (
    PriceFlicker,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class SawtoothBidExample:
    """Prints the moves and the flicker of a sawtooth bid.

    Attributes:
        flicker (PriceFlicker): The flicker over sixty ticks.
    """

    def __init__(self):
        """Builds sixty ticks one second apart.

        Returns:
            None: This method returns nothing.
        """
        start = datetime.datetime(2026, 10, 19, 15, 10, tzinfo=INDIA)
        samples = []
        for index in range(60):
            if index % 2 == 0:
                bid = decimal.Decimal('177.00')
            else:
                bid = decimal.Decimal('176.80')
            samples.append((start + datetime.timedelta(seconds=index), bid))
        self.flicker = PriceFlicker('BUY', 5, samples)

    def run(self):
        """Prints the count of each move and three percentiles.

        Returns:
            None: This method returns nothing.
        """
        moves = self.flicker.moves()
        print(f'Moves measured: {len(moves)}, of which zero: {moves.count(decimal.Decimal(0))}')
        for percentile in (40, 50, 90):
            print(f'{percentile}th percentile: {self.flicker.distance(percentile)}')


if __name__ == '__main__':
    SawtoothBidExample().run()
