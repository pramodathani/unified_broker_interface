"""Shows when the daily figures are left out: a newly listed instrument, a missing close, and a long history.

A volatility from a handful of days says little, so both figures need at least ten days. A close of zero cannot give a return, so it leaves the volatility out. A long history is cut to its last twenty days, so an old burst of trading does not count. This program builds the bars by hand, so it reads no database.

Notice that the long history's average volume is 1,000, not the 10 million it traded a month earlier.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/daily_liquidity/DailyLiquidity/example_2_too_few_days.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.daily_liquidity import (
    DailyLiquidity,
)


class TooFewDaysExample:
    """Builds three instruments' bars and prints their figures.

    Attributes:
        cases (list): Tuples of a name and its `DailyLiquidity`.
    """

    def __init__(self):
        """Builds the three cases.

        Returns:
            None: This method returns nothing.
        """
        hundred = decimal.Decimal(100)
        self.cases = [
            ('listed six days ago', DailyLiquidity([hundred] * 6, [5000] * 6)),
            ('a close of zero', DailyLiquidity([hundred] * 10 + [decimal.Decimal(0)] + [hundred] * 10, [5000] * 20)),
            ('thirty days of history', DailyLiquidity([hundred] * 30, [10000000] * 10 + [1000] * 20)),
        ]

    def run(self):
        """Prints each case's figures.

        Returns:
            None: This method returns nothing.
        """
        for name, liquidity in self.cases:
            print(f'{name}: volatility {liquidity.volatility()}, average volume {liquidity.average_volume()}, closes kept {len(liquidity.closes)}')


if __name__ == '__main__':
    TooFewDaysExample().run()
