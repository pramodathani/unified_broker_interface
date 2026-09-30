"""Prices a Nifty call and put of the same strike with the Black-76 model and prints their premiums and deltas.

`Black76` values a European option from the forward price, which for an Indian index option is the future of the same expiry. This program builds one call and one put at the 25000 strike, seven days from expiry, with the future at 25120 and a 6.5% interest rate, and prices both at a volatility of 12.5%.

It needs no market data at all, because every input is given. Notice that the call is in the money and so worth more than the put, that the call's delta is between 0 and 1 while the put's is between -1 and 0, and that the two deltas differ by the discount factor, which is the put-call parity of the model. The program also prints the two standardised distances, d1 and d2, and the normal distribution at d1, which are the pieces the premium is built from.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/black76/Black76/example_1_pricing_a_call_and_a_put.py
"""

import math

from unified_broker_interface.utilities.order_engine.utilities.black76 import (
    Black76,
)


class CallAndPutExample:
    """Prices a call and a put on the same forward and strike and prints what the model gives.

    Attributes:
        volatility (float): The volatility both options are priced at.
        call (Black76): The call.
        put (Black76): The put.
    """

    def __init__(self):
        """Builds the two options seven days from expiry.

        Returns:
            None: This method returns nothing.
        """
        years = 7 / 365
        self.volatility = 0.125
        self.call = Black76(25120.0, 25000.0, years, 0.065, True)
        self.put = Black76(25120.0, 25000.0, years, 0.065, False)

    def run(self):
        """Prints the distances, premiums and deltas of both options.

        Returns:
            None: This method returns nothing.
        """
        first, second = self.call.distances(self.volatility)
        print(f'd1 = {first:.6f}, d2 = {second:.6f}')
        print(f'N(d1) = {self.call.normal_distribution(first):.6f}')
        print(f'N(0) = {self.call.normal_distribution(0.0):.6f}')
        call_premium = self.call.price(self.volatility)
        put_premium = self.put.price(self.volatility)
        print(f'Call premium: {call_premium:.2f}')
        print(f'Put premium: {put_premium:.2f}')
        call_delta = self.call.delta(self.volatility)
        put_delta = self.put.delta(self.volatility)
        print(f'Call delta: {call_delta:.4f}')
        print(f'Put delta: {put_delta:.4f}')
        discount = math.exp(-self.call.rate * self.call.years)
        print(f'Call delta minus put delta: {call_delta - put_delta:.6f}')
        print(f'Discount factor: {discount:.6f}')
        parity = (self.call.forward - self.call.strike) * discount
        print(f'Call minus put premium: {call_premium - put_premium:.2f}, discounted forward minus strike: {parity:.2f}')


if __name__ == '__main__':
    CallAndPutExample().run()
