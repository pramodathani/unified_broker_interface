"""Builds the four legs of an iron condor, in the order a basket sends them.

An `OrderLegs` is what a basket hands to the placement of its first leg, which is the leg that chooses the broker for all of them. The lowest-cost selector's funds check then prices every leg, not only the first, and with `hedge_benefit` set it prices them as one hedged strategy at the brokers known to allow that. This program builds the legs with small stand-in orders, so it needs nothing running.

Notice that the bought legs come first. A broker checks each order's margin as it arrives, so sending the protection first keeps the peak requirement low.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/order_legs/OrderLegs/example_1_iron_condor_legs.py
"""

from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)


class StandInOrder:
    """An order carrying only a side and a quantity.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        quantity (int): The quantity in units.
    """

    def __init__(self, transaction_type, quantity):
        """Builds the order.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            quantity (int): The quantity in units.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.quantity = quantity


class IronCondorLegsExample:
    """Builds the condor's legs and prints them.

    Attributes:
        legs (OrderLegs): The four legs.
    """

    def __init__(self):
        """Builds the legs, bought ones first, asking for hedge benefit.

        Returns:
            None: This method returns nothing.
        """
        self.legs = OrderLegs(
            [
                ('nifty-2026-10-06-23200-ce', StandInOrder('BUY', 65)),
                ('nifty-2026-10-06-22400-pe', StandInOrder('BUY', 65)),
                ('nifty-2026-10-06-23000-ce', StandInOrder('SELL', 65)),
                ('nifty-2026-10-06-22600-pe', StandInOrder('SELL', 65)),
            ],
            hedge_benefit=True,
        )

    def run(self):
        """Prints the instrument and side of each leg, and the hedge flag.

        Returns:
            None: This method returns nothing.
        """
        instrument_ids = self.legs.instrument_ids()
        orders = self.legs.orders()
        for position in range(len(instrument_ids)):
            order = orders[position]
            print(f'{position + 1}. {order.transaction_type} {order.quantity} of {instrument_ids[position]}')
        print(f'Hedge benefit asked for: {self.legs.hedge_benefit}')


if __name__ == '__main__':
    IronCondorLegsExample().run()
