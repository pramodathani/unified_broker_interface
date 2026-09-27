"""The Black-76 model: an option's fair premium, delta and implied volatility from its forward price."""

import math

LOWEST_VOLATILITY = 0.0001
HIGHEST_VOLATILITY = 5.0
SEARCH_STEPS = 100


class Black76:
    """One European option on a forward price, priced by the Black-76 model.

    Black-76 is the model Indian index options are usually quoted against, because the future of the same expiry is the natural forward. Every number here is a float: a premium from a model is an estimate, and it is rounded onto the tick as a decimal only when it becomes an order price.

    Attributes:
        forward (float): The forward price, such as the future of the option's expiry.
        strike (float): The strike price.
        years (float): Time to expiry, in years of 365 days.
        rate (float): The interest rate used to discount, as a fraction such as 0.065.
        is_call (bool): True for a call, False for a put.
    """

    def __init__(self, forward, strike, years, rate, is_call):
        """Builds the model for one option.

        Args:
            forward (float): The forward price.
            strike (float): The strike price.
            years (float): Time to expiry, in years.
            rate (float): The interest rate, as a fraction.
            is_call (bool): True for a call, False for a put.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the forward, the strike or the time to expiry is not above zero.
        """
        if forward <= 0 or strike <= 0 or years <= 0:
            raise ValueError(
                f'Black-76 needs a forward, strike and time above zero, not '
                f'{forward=}, {strike=}, {years=}'
            )
        self.forward = forward
        self.strike = strike
        self.years = years
        self.rate = rate
        self.is_call = is_call

    def normal_distribution(self, value):
        """The standard normal cumulative distribution at one value.

        Args:
            value (float): The value.

        Returns:
            float: The probability that a standard normal variable is at or below it.
        """
        return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))

    def distances(self, volatility):
        """The model's two standardised distances, d1 and d2.

        Args:
            volatility (float): The volatility, as a fraction such as 0.125.

        Returns:
            tuple: d1 (float) and d2 (float).
        """
        spread = volatility * math.sqrt(self.years)
        first = (
            math.log(self.forward / self.strike)
            + volatility * volatility * self.years / 2.0
        ) / spread
        return first, first - spread

    def price(self, volatility):
        """The option's fair premium at one volatility.

        Args:
            volatility (float): The volatility, as a fraction.

        Returns:
            float: The premium.
        """
        first, second = self.distances(volatility)
        discount = math.exp(-self.rate * self.years)
        if self.is_call:
            value = (
                self.forward * self.normal_distribution(first)
                - self.strike * self.normal_distribution(second)
            )
        else:
            value = (
                self.strike * self.normal_distribution(-second)
                - self.forward * self.normal_distribution(-first)
            )
        return discount * value

    def delta(self, volatility):
        """How much the premium moves per point of the forward, at one volatility.

        Args:
            volatility (float): The volatility, as a fraction.

        Returns:
            float: The delta, between 0 and 1 for a call and between -1 and 0 for a put.
        """
        first, _ = self.distances(volatility)
        discount = math.exp(-self.rate * self.years)
        if self.is_call:
            return discount * self.normal_distribution(first)
        return -discount * self.normal_distribution(-first)

    def implied_volatility(self, premium):
        """The volatility at which the model's premium equals a given one, found by halving the interval.

        Args:
            premium (float): The premium.

        Returns:
            float | None: The volatility, or None when no volatility between 0.01% and 500% gives that premium.
        """
        low = LOWEST_VOLATILITY
        high = HIGHEST_VOLATILITY
        if premium < self.price(low) or premium > self.price(high):
            return None
        for _ in range(SEARCH_STEPS):
            middle = (low + high) / 2.0
            if self.price(middle) < premium:
                low = middle
            else:
                high = middle
        return (low + high) / 2.0
