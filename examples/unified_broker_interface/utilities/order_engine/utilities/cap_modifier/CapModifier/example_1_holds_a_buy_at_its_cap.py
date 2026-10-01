"""Holds a buy's limit at its cap, whether the pricing works it out when the order is sent or when it moves.

`CapModifier.capped_body` changes a priced body's limit, and `capped` works on a single price, which is what a moving order's new limit goes through. A buy is held at or below the cap. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/cap_modifier/CapModifier/example_1_holds_a_buy_at_its_cap.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.cap_modifier import (
    CapModifier,
)


class HoldsABuyAtItsCapExample:
    """Prints a buy's prices held at a cap."""

    def run(self):
        """Prints each price.

        Returns:
            None: This method returns nothing.
        """
        cap = CapModifier(decimal.Decimal('1000.10'))
        print(f'A body priced at 1000.25: {cap.capped_body({"order_type": "LIMIT", "price": "1000.25"}, "BUY")}')
        print(f'A body priced at 999.90: {cap.capped_body({"order_type": "LIMIT", "price": "999.90"}, "BUY")}')
        print(f'A move to 1000.40 becomes {cap.capped(decimal.Decimal("1000.40"), "BUY")}')
        print(f'As a dry run shows it: {cap.described()}')


if __name__ == '__main__':
    HoldsABuyAtItsCapExample().run()
