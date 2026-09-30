"""Follows one broker order through its states and asks, at each step, whether it is live or finished.

An `OrderLeg` is one order the engine actually sends to a broker on behalf of a parent order. It starts `planned`, is written as `sending` before the request leaves the machine, and moves on as the broker answers and the order fills.

The program walks one leg through a realistic life, from `planned` to `filled`, and prints `is_live()` and `is_finished()` after each step. It then shows the two states that are neither live nor finished in the obvious way: `sending`, where the request may or may not have reached the broker, and `unknown`, which is deliberately not finished so the engine never treats an order it cannot see as gone.

Nothing here touches a store or a broker; the leg is plain data.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_leg/OrderLeg/example_1_a_leg_through_its_states.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


class LegThroughItsStatesExample:
    """Moves one entry leg through its states and prints what the leg says about itself.

    Attributes:
        leg (OrderLeg): The leg being followed.
    """

    def __init__(self):
        """Builds a planned entry leg for 10 shares of Infosys at Zerodha.

        Returns:
            None: This method returns nothing.
        """
        self.leg = OrderLeg('p-51c2:1', 'entry')
        self.leg.broker = 'zerodha'
        self.leg.instrument_id = 'NSE:INFY'
        self.leg.transaction_type = 'BUY'
        self.leg.order_type = 'LIMIT'
        self.leg.quantity = 10
        self.leg.price = 1520.5

    def show(self):
        """Prints the leg's state and what it says about itself.

        Returns:
            None: This method returns nothing.
        """
        print(f'{self.leg.state:17} filled={self.leg.filled_quantity:2} live={self.leg.is_live()} finished={self.leg.is_finished()}')

    def run(self):
        """Walks the leg from planned to filled, then shows the unknown state.

        Returns:
            None: This method returns nothing.
        """
        self.show()
        self.leg.state = 'sending'
        self.leg.requested_at = '2026-09-30T09:20:01.125000+05:30'
        self.show()
        self.leg.state = 'sent'
        self.leg.outcome = 'accepted'
        self.leg.broker_order_id = '250930000123456'
        self.show()
        self.leg.state = 'acknowledged'
        self.leg.exchange_order_id = '1100000012345678'
        self.show()
        self.leg.state = 'partially_filled'
        self.leg.filled_quantity = 4
        self.show()
        self.leg.state = 'filled'
        self.leg.filled_quantity = 10
        self.leg.average_price = 1520.35
        self.show()
        lost_leg = OrderLeg('p-51c2:2', 'stop')
        lost_leg.state = 'unknown'
        print(f'a stop leg whose answer was lost: live={lost_leg.is_live()} finished={lost_leg.is_finished()}')


if __name__ == '__main__':
    LegThroughItsStatesExample().run()
