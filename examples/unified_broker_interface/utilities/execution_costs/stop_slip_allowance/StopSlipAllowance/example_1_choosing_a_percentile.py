"""Works out the slip allowance at several percentiles from forty measured stops.

A `StopSlipAllowance` holds the measured slips of recent stops, in basis points of their trigger, for each segment and side. `basis_points` gives a percentile of them, the slip that share of stops stayed within, and `fraction` gives the same as a share of the trigger. This program builds forty slips spread like those of 19 October 2026, most near 16 basis points and a few far beyond.

Notice how quickly the allowance grows near the top: the last few stops in a hundred slipped several times as far as the typical one, and `percentile` shows the nearest-rank rule it uses.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/stop_slip_allowance/StopSlipAllowance/example_1_choosing_a_percentile.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.stop_slip_allowance import (
    StopSlipAllowance,
)

SEGMENT = 'nse_equity_index_options'


class ChoosingAPercentileExample:
    """Prints the allowance at four percentiles.

    Attributes:
        allowance (StopSlipAllowance): The allowance over forty slips.
    """

    def __init__(self):
        """Builds forty slips: thirty small, seven middling and three large.

        Returns:
            None: This method returns nothing.
        """
        slips = []
        for index in range(30):
            slips.append(decimal.Decimal(10 + index % 10))
        for index in range(7):
            slips.append(decimal.Decimal(40 + index * 3))
        for value in ('80', '120', '200'):
            slips.append(decimal.Decimal(value))
        self.allowance = StopSlipAllowance({(SEGMENT, 'SELL'): slips})

    def run(self):
        """Prints the count and each percentile's allowance.

        Returns:
            None: This method returns nothing.
        """
        print(f'Measured sell stops: {self.allowance.stop_count(SEGMENT, "SELL")}')
        for percentile in (50, 75, 90, 95):
            basis_points = self.allowance.basis_points(SEGMENT, 'SELL', percentile)
            fraction = self.allowance.fraction(SEGMENT, 'SELL', percentile)
            print(f'{percentile}th percentile: {basis_points} bps, a share of {fraction}')
        print(f'Nearest rank of [1, 2, 3, 4] at the 50th: {self.allowance.percentile([1, 2, 3, 4], 50)}')
        print(f'Buy stops measured: {self.allowance.stop_count(SEGMENT, "BUY")}, allowance {self.allowance.basis_points(SEGMENT, "BUY")}')


if __name__ == '__main__':
    ChoosingAPercentileExample().run()
