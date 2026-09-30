"""Prices an iron condor with and without hedge benefit, with its legs sent in two different orders.

`required` gives the highest margin reached while the legs go out one by one, because a broker checks each order as it arrives. With hedge benefit, options on one underlying and expiry are charged their most possible loss at expiry, plus exposure on each sold leg, plus the premium of each bought leg. This program prices the NIFTY condor sent to every broker's calculator on 2026-09-30, at that morning's prices.

Notice that with the bought legs first and hedge benefit, the estimate is about 75,790, beside Groww's 75,614.55, Shoonya's 75,406.56 and Dhan's 75,923.77. Without hedge benefit the four legs add up to more than four times as much, and sending the sold legs first needs that much at the start even with hedge benefit, because two sold options with nothing bought yet can lose without limit.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/margin_estimate/MarginEstimate/example_2_iron_condor_with_and_without_hedge.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_selection.utilities.margin_estimate import (
    MarginEstimate,
)
from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
    MarginRateTable,
)
from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)

NIFTY_SPOT = decimal.Decimal('22721.25')


class StandInOrder:
    """An order carrying what the estimate reads.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        product (str): The product.
        quantity (int): The quantity in units.
        price (decimal.Decimal | None): The limit price.
        trigger_price (decimal.Decimal | None): The trigger price.
    """

    def __init__(self, transaction_type, price):
        """Builds a one-lot NRML order.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            price (decimal.Decimal): The limit price.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.product = 'NRML'
        self.quantity = 65
        self.price = price
        self.trigger_price = None


class IronCondorWithAndWithoutHedgeExample:
    """Prints the condor's requirement four ways.

    Attributes:
        estimate (MarginEstimate): The estimate.
        buys_first (list): The legs with the bought ones first.
        sells_first (list): The legs with the sold ones first.
    """

    def __init__(self):
        """Builds the NIFTY rate and the legs.

        Returns:
            None: This method returns nothing.
        """
        rows = [
            MarginRate('nse_equity_index_options', 'NIFTY', decimal.Decimal('0.0926'), decimal.Decimal('0.02')),
        ]
        self.estimate = MarginEstimate(MarginRateTable(logging.getLogger('example'), rows))
        bought = [
            self.leg(23200, 'CE', 'BUY', '19.0'),
            self.leg(22400, 'PE', 'BUY', '38.1'),
        ]
        sold = [
            self.leg(23000, 'CE', 'SELL', '51.6'),
            self.leg(22600, 'PE', 'SELL', '82.0'),
        ]
        self.buys_first = bought + sold
        self.sells_first = sold + bought

    @staticmethod
    def leg(strike_price, option_type, transaction_type, premium_text):
        """One NIFTY option leg expiring on 2026-10-06.

        Args:
            strike_price (int): The strike.
            option_type (str): `CE` or `PE`.
            transaction_type (str): `BUY` or `SELL`.
            premium_text (str): The premium.

        Returns:
            PricedLeg: The leg.
        """
        identity = {
            'segment': 'nse_equity_index_options',
            'shape': 'option',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-06',
            'strike_price': str(strike_price),
            'option_type': option_type,
        }
        premium = decimal.Decimal(premium_text)
        order = StandInOrder(transaction_type, premium)
        return PricedLeg(f'{strike_price}{option_type}', order, identity, premium, NIFTY_SPOT)

    def run(self):
        """Prints whether the legs can be hedged, then the requirement for each order of legs, with and without the benefit.

        Returns:
            None: This method returns nothing.
        """
        print(f'Can be hedged: {self.estimate.can_be_hedged(self.buys_first)}')
        first_leg = self.buys_first[0]
        print(f'Rates for each leg: total {self.estimate.total_rate(first_leg)}, exposure {self.estimate.exposure_rate(first_leg)}')
        print(f'Hedged once all four are in: {self.estimate.hedged_margin(self.buys_first):,.2f}')
        print(f'Added up once all four are in: {self.estimate.legs_margin(self.buys_first):,.2f}')
        print(f'Buys first, hedge benefit: {self.estimate.required(self.buys_first, True):,.2f}')
        print(f'Buys first, no hedge benefit: {self.estimate.required(self.buys_first, False):,.2f}')
        print(f'Sells first, hedge benefit: {self.estimate.required(self.sells_first, True):,.2f}')
        print(f'After the first two sells: {self.estimate.settled_margin(self.sells_first[:2], True):,.2f}')


if __name__ == '__main__':
    IronCondorWithAndWithoutHedgeExample().run()
