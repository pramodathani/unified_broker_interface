"""Asks for the levels of a crude oil future, whose taxes and fees are not in the charge table.

`BreakevenLevelsError` says why levels cannot be worked out, with the HTTP status the route answers. A segment with no row in `unified.charge_rates` gets 409, because guessing its charges would give a breakeven that loses. This program uses the offline suite's tables, which hold only NSE index options.

Notice the message names the table to add a row to.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/breakeven_levels/BreakevenLevelsError/example_1_a_segment_without_charges.py
"""

import decimal

from test_runs.breakeven_levels import START, BreakevenLevelsSuite
from unified_broker_interface.utilities.execution_costs.breakeven_levels import (
    BreakevenLevelsError,
)


class SegmentWithoutChargesExample:
    """Prints the error for an unknown segment.

    Attributes:
        suite (BreakevenLevelsSuite): The offline suite.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.suite = BreakevenLevelsSuite()

    def run(self):
        """Asks for the levels and prints the error.

        Returns:
            None: This method returns nothing.
        """
        service, database = self.suite.service()
        del database
        details = {'instrument_id': 'crude', 'segment': 'mcx_commodity_futures', 'shape': 'future', 'tick_size': '1'}
        try:
            service.levels(details, None, decimal.Decimal('5400'), 100, now=START)
        except BreakevenLevelsError as error:
            print(f'{error.status}: {error.message}')


if __name__ == '__main__':
    SegmentWithoutChargesExample().run()
