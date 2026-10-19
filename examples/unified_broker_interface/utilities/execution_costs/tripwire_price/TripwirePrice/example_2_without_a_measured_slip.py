"""Shows the tripwire of a new instrument with no measured stops, which falls back to the live spread, for a bought and a sold position.

When a segment and side has too few measured stops, `TripwirePrice` places the trigger the live spread plus two ticks beyond the floor. This program prices 65 option units at 177.00 with a spread of 0.20, bought and sold, at a broker charging 20 rupees an order.

Notice that the sold position's tripwire is below its floor, because a buy stop protecting it must fire before the price rises to the breakeven.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/tripwire_price/TripwirePrice/example_2_without_a_measured_slip.py
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


class WithoutAMeasuredSlipExample:
    """Prints both sides' fallback tripwires.

    Attributes:
        charge_rate (ChargeRate): The NSE index option row.
    """

    def __init__(self):
        """Builds the charge row.

        Returns:
            None: This method returns nothing.
        """
        self.charge_rate = ChargeRate('nse_equity_index_options', 'fno', decimal.Decimal('0'), decimal.Decimal('0.0015'), decimal.Decimal('0.0003553'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18'))

    def run(self):
        """Prints the floor and the tripwire on each side.

        Returns:
            None: This method returns nothing.
        """
        for opening_side in ('BUY', 'SELL'):
            breakeven = BreakevenPrice(self.charge_rate, opening_side, '177.00', 65, 20, '0.05')
            tripwire = TripwirePrice(breakeven, spread='0.20')
            print(f'{opening_side} at 177.00: floor {breakeven.price()}, tripwire {tripwire.price()} ({tripwire.source()}), {tripwire.distance_from_floor()} beyond the floor, {tripwire.distance_from_entry()} from the entry')


if __name__ == '__main__':
    WithoutAMeasuredSlipExample().run()
