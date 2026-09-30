"""Prices the exit of a long as a native stop-limit, which the exchange holds until its trigger trades.

`NativeStopPricing` turns an order into a stop-limit (`SL`) with a trigger price and a limit price. A stop resting at the exchange goes on protecting the position while the engine is down, which is why exits in brackets and cover orders use it. This program prices a sell, the side a part protecting a long sends, with a trigger at 990 and a limit at 988.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/native_stop_pricing/NativeStopPricing/example_1_stop_limit_for_a_long.py
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


class StopLimitForALongExample:
    """Prices one sell as a stop-limit.

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
        """Prints the priced body.

        Returns:
            None: This method returns nothing.
        """
        pricing = NativeStopPricing(decimal.Decimal('990'), decimal.Decimal('988'))
        body = pricing.priced_body(None, self.bodies.body('SELL'), 'SELL', {})
        print(f"{body['transaction_type']} {body['quantity']}: {body['order_type']}, trigger {body['trigger_price']}, limit {body['price']}")
        print(f'Reads quotes: {pricing.needs_prices()}; dry run shows {pricing.described()}')


if __name__ == '__main__':
    StopLimitForALongExample().run()
