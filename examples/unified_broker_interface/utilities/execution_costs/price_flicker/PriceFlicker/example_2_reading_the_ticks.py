"""Reads a bought and a sold position's flicker from a stand-in of `unified.ticks`.

`read` takes the last half hour of an instrument's stored ticks, from its latest session, and keeps the bid for a bought position or the ask for a sold one, because that is the price each one's stop watches. This program reads from the stand-in database of the offline suite, so it needs no PostgreSQL.

Notice that the bought position measures the bid falling and the sold one the ask rising, and that thirty ticks are too few to give a flicker at all.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/price_flicker/PriceFlicker/example_2_reading_the_ticks.py
"""

import datetime

from test_runs.breakeven_levels import BreakevenLevelsSuite, StandInTickDatabase
from unified_broker_interface.utilities.execution_costs.price_flicker import (
    PriceFlicker,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class ReadingTheTicksExample:
    """Reads both sides' flicker.

    Attributes:
        database (StandInTickDatabase): Sixty sawtooth ticks.
    """

    def __init__(self):
        """Builds the stand-in database.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInTickDatabase(BreakevenLevelsSuite().sawtooth_ticks())

    def run(self):
        """Reads and prints each side, then a short series.

        Returns:
            None: This method returns nothing.
        """
        now = datetime.datetime(2026, 10, 19, 15, 30, tzinfo=INDIA)
        for opening_side in ('BUY', 'SELL'):
            flicker = PriceFlicker(opening_side)
            flicker.read(self.database.connect, 'option', now)
            print(f'{opening_side}: first price {flicker.samples[0][1]}, {len(flicker.samples)} samples, flicker {flicker.distance()}')
        short = StandInTickDatabase(BreakevenLevelsSuite().sawtooth_ticks(30))
        flicker = PriceFlicker('BUY')
        flicker.read(short.connect, 'option', now)
        print(f'Thirty ticks: flicker {flicker.distance()}')


if __name__ == '__main__':
    ReadingTheTicksExample().run()
