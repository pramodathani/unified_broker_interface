"""Works out the daily volatility and volume of a calm share and of an option whose price swings.

The square-root model scales its estimate by how much the price moves in a typical day and by how much trades in a day. A share that moves half a percent a day and trades millions of units hardly moves for a large order; an option that moves ten percent a day and trades less moves a lot. This program builds the closing prices by hand, so it reads no database.

Notice that the option's volatility is about twenty times the share's.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/daily_liquidity/DailyLiquidity/example_1_a_calm_share_and_a_jumpy_option.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.daily_liquidity import (
    DailyLiquidity,
)


class CalmShareAndJumpyOptionExample:
    """Builds two instruments' bars and prints their figures.

    Attributes:
        share (DailyLiquidity): A share moving half a percent each day.
        option (DailyLiquidity): An option moving ten percent each day.
    """

    def __init__(self):
        """Builds both instruments' figures.

        Returns:
            None: This method returns nothing.
        """
        self.share = DailyLiquidity(self.closes('1500', '0.005'), [2000000] * 20)
        self.option = DailyLiquidity(self.closes('240', '0.10'), [400000] * 20)

    def closes(self, start, move):
        """Twenty-one closes that rise and fall by the same share in turn.

        Args:
            start (str): The first close.
            move (str): The daily move, as a fraction.

        Returns:
            list: The closes (decimal.Decimal), oldest first.
        """
        price = decimal.Decimal(start)
        closes = [price]
        for index in range(20):
            if index % 2 == 0:
                price = price * (1 + decimal.Decimal(move))
            else:
                price = price * (1 - decimal.Decimal(move))
            closes.append(price)
        return closes

    def run(self):
        """Prints each instrument's volatility and average volume.

        Returns:
            None: This method returns nothing.
        """
        places = decimal.Decimal('0.0001')
        print(f'Share: volatility {self.share.volatility().quantize(places)}, average volume {self.share.average_volume()}, days {len(self.share.volumes)}')
        print(f'Option: volatility {self.option.volatility().quantize(places)}, average volume {self.option.average_volume()}, days {len(self.option.volumes)}')


if __name__ == '__main__':
    CalmShareAndJumpyOptionExample().run()
