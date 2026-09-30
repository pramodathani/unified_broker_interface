"""Works out an iron condor's payoff at expiry across a range of NIFTY levels, and its worst case.

An `OptionPayoff` adds up what each leg is worth at expiry, leaving out the premiums, and finds the lowest point by trying an underlying price of zero and every strike, because the payoff only bends at the strikes. This program builds the NIFTY iron condor that every broker's margin calculator was asked about on 2026-09-30: 23200 call and 22400 put bought, 23000 call and 22600 put sold, one lot of 65 each.

Notice that between the sold strikes nothing is lost, beyond them the loss grows to 200 points and then stops, and the worst case is 200 × 65 = 13,000. Groww's calculator put this condor's SPAN at 12,761.25.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/option_payoff/OptionPayoff/example_1_iron_condor_at_expiry.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.option_payoff import (
    OptionPayoff,
)
from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)


class StandInOrder:
    """An order carrying a side and a quantity.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        quantity (int): The quantity in units.
        price (decimal.Decimal | None): The limit price, unused here.
        trigger_price (decimal.Decimal | None): The trigger price, unused here.
    """

    def __init__(self, transaction_type):
        """Builds a one-lot order.

        Args:
            transaction_type (str): `BUY` or `SELL`.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.quantity = 65
        self.price = None
        self.trigger_price = None


class IronCondorAtExpiryExample:
    """Prints the condor's payoff at several levels and its maximum loss.

    Attributes:
        payoff (OptionPayoff): The condor's payoff.
    """

    def __init__(self):
        """Builds the four legs.

        Returns:
            None: This method returns nothing.
        """
        legs = [
            self.leg(23200, 'CE', 'BUY'),
            self.leg(22400, 'PE', 'BUY'),
            self.leg(23000, 'CE', 'SELL'),
            self.leg(22600, 'PE', 'SELL'),
        ]
        self.payoff = OptionPayoff(legs)

    def leg(self, strike_price, option_type, transaction_type):
        """One NIFTY option leg expiring on 2026-10-06.

        Args:
            strike_price (int): The strike.
            option_type (str): `CE` or `PE`.
            transaction_type (str): `BUY` or `SELL`.

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
        return PricedLeg(f'{strike_price}{option_type}', StandInOrder(transaction_type), identity, None, None)

    def run(self):
        """Prints the payoff at eight NIFTY levels, then the slope and the maximum loss.

        Returns:
            None: This method returns nothing.
        """
        levels = [
            22000,
            22400,
            22500,
            22600,
            22800,
            23000,
            23100,
            23400,
        ]
        for level in levels:
            print(f'NIFTY at {level}: payoff {self.payoff.payoff_at(decimal.Decimal(level)):>9}')
        print(f'Turning points: {self.payoff.turning_points()}')
        print(f'Slope above the highest strike: {self.payoff.slope_above_highest_strike()}')
        print(f'Maximum loss: {self.payoff.maximum_loss()}')
        sold_call = self.payoff.legs[2]
        print(f'One unit of the sold 23000 call at 23100: {self.payoff.intrinsic_value(sold_call, decimal.Decimal(23100))}')


if __name__ == '__main__':
    IronCondorAtExpiryExample().run()
