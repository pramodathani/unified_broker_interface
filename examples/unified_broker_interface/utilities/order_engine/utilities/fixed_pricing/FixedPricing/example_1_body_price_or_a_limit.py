"""Prices one order body three ways with fixed pricing: as the body says, at a limit the caller named, and as a market order.

`FixedPricing` is the pricing every plan order gets unless it names another. With no settings it leaves the body's order type and price alone. `price` turns the order into a limit at that price, which is how limit-if-touched rests its limit once triggered, and `order_type` of `MARKET` drops the price. It never reads a quote, so it can price an order at any moment.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/fixed_pricing/FixedPricing/example_1_body_price_or_a_limit.py
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


class BodyPriceOrALimitExample:
    """Prices a body with three fixed pricings and prints the results.

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
        """Prints each pricing's body and how a dry run shows it.

        Returns:
            None: This method returns nothing.
        """
        for label, pricing in (
            ('as the body says', FixedPricing(None, None)),
            ('a limit at 996', FixedPricing(decimal.Decimal('996'), None)),
            ('a market order', FixedPricing(None, 'MARKET')),
        ):
            body = pricing.priced_body(None, self.bodies.body('BUY'), 'BUY', {})
            print(f"{label}: {body['order_type']} at {body.get('price')}; reads quotes {pricing.needs_prices()}")
            print(f'  dry run shows {pricing.described()}')


if __name__ == '__main__':
    BodyPriceOrALimitExample().run()
