"""Builds one broker's row of the cost table and reads its limits and brokerage.

A `BrokerCosts` is one row of `unified.broker_order_costs`: the broker's order-rate limits per second, minute, hour and day, and the brokerage it charges for one order in each of three categories. The cost table builds one per row when it reads the database. This program builds one directly, with the values Fyers had on 2026-09-29, so it needs no database.

A limit of None means the broker sets no limit for that window. The brokerage values are `decimal.Decimal`, as PostgreSQL's `numeric` columns arrive through psycopg2.

Notice that Fyers has no hourly limit and that its delivery orders cost nothing while its intraday and F&O orders cost 20 rupees each.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/broker_cost_table/BrokerCosts/example_1_reading_one_row.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
)


class ReadingOneRowExample:
    """Builds the Fyers row and prints every field.

    Attributes:
        costs (BrokerCosts): The row being shown.
    """

    def __init__(self):
        """Builds the Fyers row.

        Returns:
            None: This method returns nothing.
        """
        fees = {
            'delivery': decimal.Decimal('0'),
            'fno': decimal.Decimal('20'),
            'intraday': decimal.Decimal('20'),
        }
        self.costs = BrokerCosts('fyers', 8, 180, None, 100000, fees)

    def run(self):
        """Prints the limits and the brokerage for each category.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {self.costs.broker_name}')
        print(f'Orders per second: {self.costs.orders_per_second}')
        print(f'Orders per minute: {self.costs.orders_per_minute}')
        print(f'Orders per hour: {self.costs.orders_per_hour}')
        print(f'Orders per day: {self.costs.orders_per_day}')
        categories = [
            'delivery',
            'fno',
            'intraday',
        ]
        for category in categories:
            print(f'Brokerage for {category}: {self.costs.fee(category)}')


if __name__ == '__main__':
    ReadingOneRowExample().run()
