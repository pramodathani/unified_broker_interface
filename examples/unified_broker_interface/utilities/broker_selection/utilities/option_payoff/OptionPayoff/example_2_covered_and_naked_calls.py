"""Compares a sold call left naked with the same call covered by a bought call and by a bought future.

When more calls and futures are sold than bought, the payoff keeps falling as the underlying rises, so there is no maximum loss and `maximum_loss` answers None; the margin estimate then adds the legs up without hedge benefit. Covering the sold call caps the loss. This program builds three sets of NIFTY legs, with the future bought at 22,833.70, the price of 2026-09-30.

Notice that the call spread can lose at most 200 points, while the future and sold call together can lose most on the way down, where the future falls and the call expires worthless.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/option_payoff/OptionPayoff/example_2_covered_and_naked_calls.py
"""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.option_payoff import (
    OptionPayoff,
)
from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)


class StandInOrder:
    """An order carrying a side, a quantity and a limit price.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        quantity (int): The quantity in units.
        price (decimal.Decimal | None): The limit price.
        trigger_price (decimal.Decimal | None): The trigger price.
    """

    def __init__(self, transaction_type, price=None):
        """Builds a one-lot order.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            price (decimal.Decimal | None): The limit price.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.quantity = 65
        self.price = price
        self.trigger_price = None


class CoveredAndNakedCallsExample:
    """Prints the maximum loss of three sets of legs.

    Attributes:
        cases (list): `(description, OptionPayoff)` tuples.
    """

    def __init__(self):
        """Builds the three sets.

        Returns:
            None: This method returns nothing.
        """
        sold_call = self.call(23000, 'SELL')
        self.cases = [
            ('23000 call sold alone', OptionPayoff([sold_call])),
            ('covered by the 23200 call', OptionPayoff([sold_call, self.call(23200, 'BUY')])),
            ('covered by a bought future', OptionPayoff([sold_call, self.future()])),
        ]

    def call(self, strike_price, transaction_type):
        """A NIFTY call expiring on 2026-10-27.

        Args:
            strike_price (int): The strike.
            transaction_type (str): `BUY` or `SELL`.

        Returns:
            PricedLeg: The leg.
        """
        identity = {
            'segment': 'nse_equity_index_options',
            'shape': 'option',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-27',
            'strike_price': str(strike_price),
            'option_type': 'CE',
        }
        return PricedLeg(f'{strike_price}CE', StandInOrder(transaction_type), identity, None, None)

    def future(self):
        """The NIFTY October future, bought at 22,833.70.

        Returns:
            PricedLeg: The leg.
        """
        identity = {
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-27',
            'strike_price': None,
            'option_type': None,
        }
        order = StandInOrder('BUY', decimal.Decimal('22833.7'))
        return PricedLeg('NIFTYFUT', order, identity, decimal.Decimal('22833.7'), None)

    def run(self):
        """Prints each set's slope above the strikes and its maximum loss.

        Returns:
            None: This method returns nothing.
        """
        for description, payoff in self.cases:
            print(f'{description}: slope {payoff.slope_above_highest_strike()}, maximum loss {payoff.maximum_loss()}')


if __name__ == '__main__':
    CoveredAndNakedCallsExample().run()
