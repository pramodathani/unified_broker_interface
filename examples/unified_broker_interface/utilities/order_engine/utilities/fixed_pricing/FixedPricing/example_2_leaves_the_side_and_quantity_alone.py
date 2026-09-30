"""Shows that fixed pricing changes only the order type and price, leaving the side, quantity and everything else as the part set them.

`FixedPricing` is handed a copy of the body after the part has already chosen the side, for example flipping a buy to a sell for a part that protects a position. It changes only `order_type` and `price`, so the rest of the order is exactly what the part sent it. This program prices a sell body for a protecting part with a limit, and a body whose order type the caller set to `MARKET` while also naming a price, which is dropped.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/fixed_pricing/FixedPricing/example_2_leaves_the_side_and_quantity_alone.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class PricingExampleBody:
    """Builds the caller's order body the pricing examples price."""

    def body(self, transaction_type):
        """A limit order for ten RELIANCE shares at 1,000.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            dict: The body.
        """
        return {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': transaction_type,
            'order_type': 'LIMIT',
            'quantity': 10,
            'price': '1000.00',
        }


class LeavesTheSideAndQuantityAloneExample:
    """Prices two bodies and prints every field before and after.

    Attributes:
        bodies (PricingExampleBody): Builds the body.
    """

    def __init__(self):
        """Builds the body maker.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = PricingExampleBody()

    def run(self):
        """Prints the bodies before and after pricing.

        Returns:
            None: This method returns nothing.
        """
        sell = self.bodies.body('SELL')
        print(f'Before: {sell}')
        priced = FixedPricing(decimal.Decimal('1004.50'), 'LIMIT').priced_body(None, dict(sell), 'SELL', {})
        print(f'Limit at 1004.50: {priced}')
        market = FixedPricing(decimal.Decimal('1004.50'), 'MARKET').priced_body(None, dict(sell), 'SELL', {})
        print(f'Market: {market}')
        print(f"Dry run of the market pricing: {FixedPricing(decimal.Decimal('1004.50'), 'MARKET').described()}")
        print(f'Reads quotes: {FixedPricing(None, None).needs_prices()}')


if __name__ == '__main__':
    LeavesTheSideAndQuantityAloneExample().run()
