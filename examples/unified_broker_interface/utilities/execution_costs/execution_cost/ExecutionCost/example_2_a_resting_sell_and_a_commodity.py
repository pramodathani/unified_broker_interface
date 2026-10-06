"""Measures a sell that rested and filled at the ask, a crude oil buy, and a leg whose quote was missing.

A resting sell filled at the ask earns the spread instead of paying it, so its beyond-the-touch part is negative and cancels the half spread. A commodity fill can be reported in lots, so it gets basis points but no rupee total. A leg with no recent quote at the decision has no total at all. This program builds the legs and quotes by hand, so it reads no database.

Notice the sell's total of -0.25 per unit, a gain, and the crude oil row's empty rupee column.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/execution_cost/ExecutionCost/example_2_a_resting_sell_and_a_commodity.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.execution_cost import (
    ExecutionCost,
)
from unified_broker_interface.utilities.execution_costs.leg_execution import (
    LegExecution,
)
from unified_broker_interface.utilities.execution_costs.quote_moment import (
    QuoteMoment,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class RestingSellAndCommodityExample:
    """Prints three legs' costs.

    Attributes:
        moment (datetime.datetime): When every leg was decided on.
    """

    def __init__(self):
        """Builds the example.

        Returns:
            None: This method returns nothing.
        """
        self.moment = datetime.datetime(2026, 10, 6, 21, 0, 0, tzinfo=INDIA)

    def leg(self, transaction_type, filled_quantity, average_price):
        """Builds a filled leg.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            filled_quantity (int): The quantity filled.
            average_price (str): The fill price.

        Returns:
            LegExecution: The leg.
        """
        leg = LegExecution('7f9c0a52-0c1e-4f7b-9d4a-3b2e1c0d9e8f', '1', self.moment)
        leg.transaction_type = transaction_type
        leg.filled_quantity = filled_quantity
        leg.average_price = decimal.Decimal(average_price)
        return leg

    def quote(self, bid, ask):
        """Builds a quote at the example's moment.

        Args:
            bid (str): The best bid.
            ask (str): The best ask.

        Returns:
            QuoteMoment: The quote.
        """
        return QuoteMoment(self.moment, decimal.Decimal(bid), decimal.Decimal(ask))

    def run(self):
        """Prints each leg's parts and totals.

        Returns:
            None: This method returns nothing.
        """
        option_quote = self.quote('238.20', '238.70')
        resting_sell = ExecutionCost(self.leg('SELL', 65, '238.70'), option_quote, option_quote, option_quote, 'nse_equity_index_options', True)
        crude_quote = self.quote('5210', '5211')
        crude_buy = ExecutionCost(self.leg('BUY', 1, '5212'), crude_quote, crude_quote, crude_quote, 'mcx_commodity_futures', False)
        no_quote = ExecutionCost(self.leg('BUY', 50, '41.25'), None, None, None, 'nse_equity_options', True)
        costs = [
            ('resting sell', resting_sell),
            ('crude oil buy', crude_buy),
            ('no quote', no_quote),
        ]
        for name, cost in costs:
            row = cost.row()
            print(f"{name}: half spread {row['half_spread_cost']}, beyond the touch {row['beyond_touch_cost']}, total {row['total_cost']}, {row['total_cost_basis_points']} bps, {row['total_cost_rupees']} rupees")
        print(f'Quote time {resting_sell.quote_time(option_quote).time()}, mid {resting_sell.mid(option_quote)}, and with no quote {resting_sell.mid(None)}')
        print(f"Rounded to the table's places: {resting_sell.rounded(decimal.Decimal('238.123456'))}")
        print(f"Minus zero written as: {resting_sell.without_sign_on_zero(decimal.Decimal('-0.0000'))}")


if __name__ == '__main__':
    RestingSellAndCommodityExample().run()
