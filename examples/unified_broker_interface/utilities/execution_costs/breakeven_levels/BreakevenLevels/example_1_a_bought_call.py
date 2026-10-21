"""Works out all three levels of a NIFTY call bought at 177.00, as `/api/instruments/breakeven` answers them.

A `BreakevenLevels` service reads the charge rates, the broker costs and the measured stop slips once a day, reads the instrument's flicker from its ticks, and answers the floor, the tripwire and the switch-on. This program uses the in-memory tables and stand-in database of the offline suite, so it needs no PostgreSQL: forty stops that slipped 58 basis points, and a bid that dips 0.20 every other second.

Notice that the cheapest broker is chosen when none is named, and that naming a broker charging 20 rupees an order moves the floor up by 0.70.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/breakeven_levels/BreakevenLevels/example_1_a_bought_call.py
"""

import datetime
import decimal
import json

from test_runs.breakeven_levels import START, SEGMENT, BreakevenLevelsSuite


class BoughtCallExample:
    """Prints the levels answer.

    Attributes:
        suite (BreakevenLevelsSuite): The offline suite, whose stand-ins this uses.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.suite = BreakevenLevelsSuite()

    def run(self):
        """Prints the answer at the cheapest broker and the floor at a dearer one.

        Returns:
            None: This method returns nothing.
        """
        slips = []
        for index in range(40):
            slips.append((SEGMENT, 'SELL', decimal.Decimal('58')))
        service, database = self.suite.service(self.suite.sawtooth_ticks(), slips)
        answer = service.levels(self.suite.details(), self.suite.quote(), decimal.Decimal('177'), 65, now=START)
        print(json.dumps(answer, indent=1))
        dearer = service.levels(self.suite.details(), self.suite.quote(), decimal.Decimal('177'), 65, broker='zerodha', now=START)
        print(f'At zerodha the floor is {dearer["floor"]["price"]}')
        print(f'Tables read today: {service.loaded_on}; refreshed again: {service.refresh(START + datetime.timedelta(hours=1))}; ticks read {database.tick_reads} times')
        print(f'The cheapest F&O broker: {service.cheapest_broker("fno")}; the spread of an empty book: {service.spread({})}')
        print(f'As text: {service.text(decimal.Decimal("1.50"))}')


if __name__ == '__main__':
    BoughtCallExample().run()
