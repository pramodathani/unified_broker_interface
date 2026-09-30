"""Compares several brokers' rows to find the cheapest broker for each kind of order, and shows what an unknown category does.

The lowest-cost selector ranks brokers by `fee(category)`, where the category is `delivery` for a `CNC` order, `fno` for a future or option and `intraday` for anything else. This program does the first step of that by hand: it builds four rows with the brokerage from the table of 2026-09-29 and, for each category, lists the brokers from cheapest to dearest. It needs no database, because the rows are built directly.

`fee` looks the category up in a dictionary, so a category that is not one of the three raises `KeyError`. The program asks for `commodity` to show that.

Notice that Shoonya is cheapest for intraday and F&O orders, that Dhan, Shoonya and Zerodha tie at nothing for delivery orders, and that the tie is left in the order the rows were listed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/broker_cost_table/BrokerCosts/example_2_cheapest_broker_per_category.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
)


class CheapestBrokerPerCategoryExample:
    """Sorts four brokers by brokerage in each category.

    Attributes:
        rows (list): The `BrokerCosts` rows being compared.
    """

    def __init__(self):
        """Builds four rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = [
            BrokerCosts('dhan', 9, 480, 7000, None, self.fees('0', '20', '20')),
            BrokerCosts('groww', 9, 240, None, None, self.fees('20', '20', '20')),
            BrokerCosts('shoonya', 8, 540, None, None, self.fees('0', '5', '5')),
            BrokerCosts('zerodha', 9, 375, None, 4500, self.fees('0', '20', '20')),
        ]

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
        """Prints each category's brokers from cheapest to dearest, then asks for an unknown category.

        Returns:
            None: This method returns nothing.
        """
        categories = [
            'delivery',
            'fno',
            'intraday',
        ]
        for category in categories:
            priced = []
            for costs in self.rows:
                priced.append((costs.fee(category), costs.broker_name))
            priced.sort(key=lambda pair: pair[0])
            listing = []
            for fee, broker_name in priced:
                listing.append(f'{broker_name} {fee}')
            print(f'{category}: {", ".join(listing)}')
        try:
            self.rows[0].fee('commodity')
        except KeyError as error:
            print(f'fee("commodity") raised KeyError for {error}')


if __name__ == '__main__':
    CheapestBrokerPerCategoryExample().run()
