"""Shows a cap on a sell, which is a floor, and a market order, which has no limit to cap.

`CapModifier.capped` holds a sell at or above the cap. `capped_body` leaves a market order alone, because it carries no price. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/cap_modifier/CapModifier/example_2_sells_and_market_orders.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.cap_modifier import (
    CapModifier,
)


class SellsAndMarketOrdersExample:
    """Prints a sell's prices held at a cap, and a market order."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        cap = CapModifier(decimal.Decimal('995.00'))
        print(f'A sell at 990.00 becomes {cap.capped(decimal.Decimal("990.00"), "SELL")}, at 999.00 stays {cap.capped(decimal.Decimal("999.00"), "SELL")}')
        print(f'A market order: {cap.capped_body({"order_type": "MARKET"}, "SELL")}')
        print(f'As a dry run shows it: {cap.described()}')


if __name__ == '__main__':
    SellsAndMarketOrdersExample().run()
