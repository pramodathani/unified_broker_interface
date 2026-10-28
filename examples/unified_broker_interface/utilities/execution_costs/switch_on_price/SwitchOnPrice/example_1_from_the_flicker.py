"""Places the switch-on of a NIFTY option bought at 177.00, from the flicker measured on 19 October 2026.

A `SwitchOnPrice` is how far the watched price must go beyond the tripwire before the stop is moved there. This program uses the tripwire of 178.50 from that day's stop slips and the 0.80 flicker of the 22850 call's bid over five seconds.

Notice that the stop only moves once the bid reaches 179.30, 2.30 above the entry, and that a sold position mirrors it below.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/switch_on_price/SwitchOnPrice/example_1_from_the_flicker.py
"""

import decimal

from test_runs.breakeven_levels import BreakevenLevelsSuite
from unified_broker_interface.utilities.execution_costs.switch_on_price import (
    SwitchOnPrice,
)


class FromTheFlickerExample:
    """Prints both sides' levels.

    Attributes:
        suite (BreakevenLevelsSuite): The offline suite, whose tripwires this uses.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.suite = BreakevenLevelsSuite()

    def run(self):
        """Prints the floor, tripwire and switch-on of each side.

        Returns:
            None: This method returns nothing.
        """
        for opening_side in ('BUY', 'SELL'):
            tripwire = self.suite.tripwire(opening_side)
            switch_on = SwitchOnPrice(tripwire, decimal.Decimal('0.80'))
            print(f'{opening_side} at 177.00: floor {tripwire.breakeven.price()}, tripwire {tripwire.price()}, switch-on {switch_on.price()} ({switch_on.source()}), {switch_on.distance_from_tripwire()} beyond the tripwire, {switch_on.distance_from_entry()} from the entry')


if __name__ == '__main__':
    FromTheFlickerExample().run()
