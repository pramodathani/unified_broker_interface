"""Builds a levels answer from its parts, to show what each field of `/api/instruments/breakeven` means.

`answer` puts a floor, a tripwire and a switch-on into the route's JSON shape, prices as text so no digit is lost. This program builds the three levels by hand for a put sold at 177.00 and passes them in.

Notice that a sold position's levels all sit below the entry, and that `distance_from_entry` is still positive, because it counts in the direction the position needs the price to go.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/breakeven_levels/BreakevenLevels/example_2_answer_parts.py
"""

import decimal

from test_runs.breakeven_levels import BreakevenLevelsSuite
from unified_broker_interface.utilities.execution_costs.price_flicker import (
    PriceFlicker,
)
from unified_broker_interface.utilities.execution_costs.switch_on_price import (
    SwitchOnPrice,
)


class AnswerPartsExample:
    """Prints a sold position's answer.

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
        """Builds and prints the answer's levels.

        Returns:
            None: This method returns nothing.
        """
        service, database = self.suite.service()
        del database
        tripwire = self.suite.tripwire('SELL')
        switch_on = SwitchOnPrice(tripwire, decimal.Decimal('0.80'))
        answer = service.answer(self.suite.details(), tripwire.breakeven, tripwire, switch_on, PriceFlicker('SELL'), decimal.Decimal('0.20'), 'fno', 'flattrade', 90, self.suite.option_rate())
        for name in ('floor', 'tripwire', 'switch_on'):
            print(f'{name}: {answer[name]["price"]}, {answer[name]["distance_from_entry"]} from the entry')
        print(f'Side {answer["opening_side"]}, spread {answer["spread"]}, charges checked on {answer["floor"]["charges_checked_on"]}')


if __name__ == '__main__':
    AnswerPartsExample().run()
