"""Recovers the volatility implied by an option's traded premium, and shows the premiums and inputs the model refuses.

An order type that works an option at a volatility rather than at a price first asks `Black76.implied_volatility` what volatility the market's premium means. This program prices a Bank Nifty put at a known volatility, asks for the implied volatility of that premium and gets the same volatility back, and then asks for one market premium read from a quote.

The search halves an interval between 0.01% and 500%, so a premium below the option's value at the lowest volatility, such as a put quoted under its intrinsic value, has no answer and gives None. Building the model with no time left to expiry raises `ValueError`, because the model divides by the square root of the time. Nothing here reads market data; every number is given.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/black76/Black76/example_2_implied_volatility_from_a_premium.py
"""

from unified_broker_interface.utilities.order_engine.utilities.black76 import (
    Black76,
)


class ImpliedVolatilityExample:
    """Finds implied volatilities for a put and shows the cases that have none.

    Attributes:
        put (Black76): A Bank Nifty put, 21 days from expiry.
    """

    def __init__(self):
        """Builds the put with the future at 55200 and the strike at 55500.

        Returns:
            None: This method returns nothing.
        """
        self.put = Black76(55200.0, 55500.0, 21 / 365, 0.065, False)

    def run(self):
        """Prints the round trip, a market premium's volatility, and the refusals.

        Returns:
            None: This method returns nothing.
        """
        premium = self.put.price(0.14)
        print(f'Premium at 14.00% volatility: {premium:.2f}')
        recovered = self.put.implied_volatility(premium)
        print(f'Implied volatility of that premium: {recovered * 100:.2f}%')
        market_premium = 812.40
        implied = self.put.implied_volatility(market_premium)
        print(f'Implied volatility of a {market_premium:.2f} premium: {implied * 100:.2f}%')
        print(f'Delta at that volatility: {self.put.delta(implied):.4f}')
        too_cheap = 250.0
        print(f'Implied volatility of a {too_cheap:.2f} premium: {self.put.implied_volatility(too_cheap)}')
        try:
            Black76(55200.0, 55500.0, 0.0, 0.065, False)
        except ValueError as error:
            print(f'ValueError: {error}')


if __name__ == '__main__':
    ImpliedVolatilityExample().run()
