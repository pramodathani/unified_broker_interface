"""Looks up brokers' rows and order-rate limits in a cost table built from rows in memory.

A `BrokerCostTable` normally fills itself from `unified.broker_order_costs` when its process calls `start`. A caller that does not read the database can hand it rows instead, which is what this program does, with three rows from the table of 2026-09-29. It then asks the questions the selector, the rate budget and the daily order count ask while an order is being placed: one broker's row, its per-second and per-day limits, and every broker that has a per-day limit.

A broker the table has no row for, Groww here, answers None to every question, which tells the caller to fall back to the limits in configuration. The program also asks how long the daily reload thread would wait from two pinned moments, so the answer does not depend on when it runs.

Notice that Dhan has a per-second limit but no per-day one, so only Fyers and Zerodha appear among the day-capped brokers, and that at 05:30 IST the next reload is half an hour away while at 06:00 exactly it is a whole day away.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/broker_cost_table/BrokerCostTable/example_1_looking_up_limits.py
"""

import datetime
import decimal
import logging

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
    BrokerCostTable,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)


class LookingUpLimitsExample:
    """Builds a table from three rows and prints what it answers.

    Attributes:
        table (BrokerCostTable): The table being shown.
    """

    def __init__(self):
        """Builds the table from three rows held in memory.

        Returns:
            None: This method returns nothing.
        """
        rows = {
            'dhan': BrokerCosts('dhan', 9, 480, 7000, None, self.fees('0', '20', '20')),
            'fyers': BrokerCosts('fyers', 8, 180, None, 100000, self.fees('0', '20', '20')),
            'zerodha': BrokerCosts('zerodha', 9, 375, None, 4500, self.fees('0', '20', '20')),
        }
        self.table = BrokerCostTable(logging.getLogger('example'), rows)

    @staticmethod
    def fees(delivery, fno, intraday):
        """Builds one broker's brokerage dictionary.

        Args:
            delivery (str): The brokerage for a delivery order.
            fno (str): The brokerage for a futures or options order.
            intraday (str): The brokerage for an intraday order.

        Returns:
            dict: The brokerage (decimal.Decimal) by category.
        """
        return {
            'delivery': decimal.Decimal(delivery),
            'fno': decimal.Decimal(fno),
            'intraday': decimal.Decimal(intraday),
        }

    def run(self):
        """Prints each broker's row and limits, the day-capped brokers and two reload waits.

        Returns:
            None: This method returns nothing.
        """
        print(f'Categories: {BrokerCostTable.CATEGORIES}')
        broker_names = [
            'dhan',
            'fyers',
            'groww',
            'zerodha',
        ]
        for broker_name in broker_names:
            costs = self.table.costs(broker_name)
            has_row = costs is not None
            per_second = self.table.per_second_limit(broker_name)
            per_day = self.table.per_day_limit(broker_name)
            print(f'{broker_name}: has row {has_row}, per second {per_second}, per day {per_day}')
        print(f'Day-capped brokers: {self.table.day_capped_brokers()}')
        moments = [
            datetime.datetime(2026, 9, 30, 5, 30, tzinfo=INDIA),
            datetime.datetime(2026, 9, 30, 6, 0, tzinfo=INDIA),
        ]
        for moment in moments:
            seconds = self.table.seconds_until_reload(moment)
            print(f'From {moment.isoformat()}: next reload in {seconds} seconds')


if __name__ == '__main__':
    LookingUpLimitsExample().run()
