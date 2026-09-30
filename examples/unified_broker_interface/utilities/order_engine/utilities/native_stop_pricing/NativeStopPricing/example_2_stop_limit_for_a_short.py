"""Prices the exit of a short as a native stop-limit, a buy that triggers when the price rises through 1,010.

`NativeStopPricing` does not care which side it prices: the part decides the side, and the pricing only sets the order type and the two prices. A part protecting a short sends a buy, and its stop sits above the market. This program prices that buy, and shows that whatever order type and price the body carried are replaced.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/native_stop_pricing/NativeStopPricing/example_2_stop_limit_for_a_short.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.native_stop_pricing import (
    NativeStopPricing,
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


class StopLimitForAShortExample:
    """Prices one buy as a stop-limit and prints the body before and after.

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
        """Prints the body before and after pricing.

        Returns:
            None: This method returns nothing.
        """
        before = self.bodies.body('BUY')
        print(f'Before: {before}')
        pricing = NativeStopPricing(decimal.Decimal('1010'), decimal.Decimal('1012'))
        print(f'After: {pricing.priced_body(None, dict(before), "BUY", {})}')
        print(f'Reads quotes: {pricing.needs_prices()}; dry run shows {pricing.described()}')


if __name__ == '__main__':
    StopLimitForAShortExample().run()
