"""Builds the four legs of a NIFTY iron condor as reference legs and sorts them into bought and sold.

The calibration asks each broker's calculator about an iron condor twice, as one basket and as four separate orders, and a broker gives hedge benefit when the basket costs well under the four added up. The legs go bought ones first, as a basket sends them. This program builds them with made-up instrument ids, since only the sides matter here.

Notice that `is_buy` splits the legs two and two.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/reference_leg/ReferenceLeg/example_2_the_legs_of_a_condor.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)


class TheLegsOfACondorExample:
    """Builds the condor and prints the bought and sold legs.

    Attributes:
        legs (list): The four `ReferenceLeg` legs.
    """

    def __init__(self):
        """Builds the four legs.

        Returns:
            None: This method returns nothing.
        """
        wanted = [
            ('NIFTY 23200 CE bought call', 'BUY', '19.0'),
            ('NIFTY 22400 PE bought put', 'BUY', '38.1'),
            ('NIFTY 23000 CE sold call', 'SELL', '51.6'),
            ('NIFTY 22600 PE sold put', 'SELL', '82.0'),
        ]
        identity = {
            'segment': 'nse_equity_index_options',
            'shape': 'option',
        }
        self.legs = []
        for name, transaction_type, price_text in wanted:
            instrument = Instrument(name, identity, {})
            self.legs.append(ReferenceLeg(name, instrument, transaction_type, 'NRML', 65, decimal.Decimal(price_text)))

    def run(self):
        """Prints the bought legs, then the sold ones.

        Returns:
            None: This method returns nothing.
        """
        for wanted_buy in [True, False]:
            side = 'Bought' if wanted_buy else 'Sold'
            for leg in self.legs:
                if leg.is_buy() == wanted_buy:
                    print(f'{side}: {leg.name} at {leg.price}')


if __name__ == '__main__':
    TheLegsOfACondorExample().run()
