"""Places the switch-on of an instrument with no stored ticks, which falls back to the live spread.

When the flicker cannot be measured, `SwitchOnPrice` places the switch-on the live spread plus two ticks beyond the tripwire, like the tripwire's own fallback. This program uses a spread of 0.20 and the 0.05 tick of a NIFTY option.

Notice that the switch-on sits 0.30 beyond the tripwire, much closer than a measured flicker would put it, so with no history the stop moves up sooner.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/switch_on_price/SwitchOnPrice/example_2_without_a_flicker.py
"""

from test_runs.breakeven_levels import BreakevenLevelsSuite
from unified_broker_interface.utilities.execution_costs.switch_on_price import (
    SwitchOnPrice,
)


class WithoutAFlickerExample:
    """Prints the fallback switch-on.

    Attributes:
        switch_on (SwitchOnPrice): The switch-on from the spread.
    """

    def __init__(self):
        """Builds the switch-on.

        Returns:
            None: This method returns nothing.
        """
        self.switch_on = SwitchOnPrice(BreakevenLevelsSuite().tripwire('BUY'), spread='0.20')

    def run(self):
        """Prints the levels.

        Returns:
            None: This method returns nothing.
        """
        print(f'Tripwire: {self.switch_on.tripwire.price()}')
        print(f'Switch-on: {self.switch_on.price()} ({self.switch_on.source()})')
        print(f'Beyond the tripwire by {self.switch_on.distance_from_tripwire()}, from the entry by {self.switch_on.distance_from_entry()}')


if __name__ == '__main__':
    WithoutAFlickerExample().run()
