"""Works out the tripwire of a NIFTY option bought at 177.00, from the slip stops showed on 19 October 2026.

A `TripwirePrice` is the trigger a breakeven stop should use: far enough beyond the real breakeven that a fill slipping by the allowance still lands on it. This program uses the floor of 177.45 that the charges give, and the 90th percentile slip of that day's sell stops, 58.03 basis points.

Notice that the trigger sits 1.50 above the entry, and that a fill slipping by the whole allowance from it still lands above the floor.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/tripwire_price/TripwirePrice/example_1_a_bought_option.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.breakeven_price import (
    BreakevenPrice,
)
from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)
from unified_broker_interface.utilities.execution_costs.tripwire_price import (
    TripwirePrice,
)


class BoughtOptionTripwireExample:
    """Prints the floor, the tripwire and the worst expected fill.

    Attributes:
        tripwire (TripwirePrice): The tripwire.
    """

    def __init__(self):
        """Builds the breakeven and the tripwire.

        Returns:
            None: This method returns nothing.
        """
        charge_rate = ChargeRate('nse_equity_index_options', 'fno', decimal.Decimal('0'), decimal.Decimal('0.0015'), decimal.Decimal('0.0003553'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18'))
        breakeven = BreakevenPrice(charge_rate, 'BUY', '177.00', 65, 0, '0.05')
        self.tripwire = TripwirePrice(breakeven, decimal.Decimal('0.005803'))

    def run(self):
        """Prints the levels.

        Returns:
            None: This method returns nothing.
        """
        print(f'Entry: {self.tripwire.breakeven.entry_price}')
        print(f'Floor, the real breakeven: {self.tripwire.breakeven.price()}')
        print(f'Tripwire, exact: {self.tripwire.exact_price()}')
        print(f'Tripwire, on the tick: {self.tripwire.price()} ({self.tripwire.source()})')
        print(f'Above the floor by {self.tripwire.distance_from_floor()}, above the entry by {self.tripwire.distance_from_entry()}')
        worst = self.tripwire.price() * (1 - self.tripwire.slip_fraction)
        print(f'A fill slipping by the whole allowance: {worst:.2f}')


if __name__ == '__main__':
    BoughtOptionTripwireExample().run()
