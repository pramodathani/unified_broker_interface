"""Shows that hedge benefit is off unless the caller asks for it, and that only a true `True` turns it on.

A basket reads `hedge_benefit` from its `synthetic` object and passes `True` only when the caller wrote the JSON value `true`. `OrderLegs` itself turns whatever it is given into a plain boolean. This program builds legs three ways and prints the flag each time, with no orders at all, because the flag does not depend on them.

Notice that leaving the flag out means no hedge benefit, so a strategy is priced as its legs added up unless the caller says otherwise.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/order_legs/OrderLegs/example_2_hedge_benefit_is_off_unless_asked.py
"""

from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)


class HedgeBenefitIsOffUnlessAskedExample:
    """Builds legs with and without the flag.

    Attributes:
        cases (list): `(description, OrderLegs)` tuples.
    """

    def __init__(self):
        """Builds three sets of legs.

        Returns:
            None: This method returns nothing.
        """
        self.cases = [
            ('flag left out', OrderLegs([])),
            ('flag set to True', OrderLegs([], True)),
            ('flag set to False', OrderLegs([], False)),
        ]

    def run(self):
        """Prints each case's flag and how many legs it holds.

        Returns:
            None: This method returns nothing.
        """
        for description, legs in self.cases:
            print(f'{description}: hedge benefit {legs.hedge_benefit}, {len(legs.legs)} legs')


if __name__ == '__main__':
    HedgeBenefitIsOffUnlessAskedExample().run()
