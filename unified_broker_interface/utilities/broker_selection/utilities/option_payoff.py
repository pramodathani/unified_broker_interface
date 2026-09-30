"""The most a set of options and futures on one underlying, expiring together, can lose at expiry."""

import decimal

ZERO = decimal.Decimal(0)


class OptionPayoff:
    """The payoff at expiry of several option and future legs on the same underlying and expiry, and its worst case.

    At expiry a call is worth the amount the underlying finishes above its strike and a put the amount it finishes below, so the payoff of the whole set is made of straight lines that bend only at the strikes. Its lowest point is therefore at an underlying price of zero or at one of the strikes, unless the set keeps losing as the price rises forever, which happens when more calls and futures are sold than bought.

    Premiums are left out on purpose. The premium paid for a bought option is counted separately as money spent, and the premium received for a sold one is not counted at all, so the loss found here is never smaller than the true worst case.

    Attributes:
        legs (list): The `PricedLeg` legs.
    """

    def __init__(self, legs):
        """Builds the payoff.

        Args:
            legs (list): The `PricedLeg` legs, every one an option or a future.

        Returns:
            None: This method returns nothing.
        """
        self.legs = list(legs)

    def payoff_at(self, underlying_price):
        """What the whole set is worth at expiry, against what it was bought or sold for, leaving out option premiums.

        Args:
            underlying_price (decimal.Decimal): Where the underlying finishes.

        Returns:
            decimal.Decimal: The payoff; a negative number is a loss.

        Raises:
            ValueError: When a future has no price to measure from or an option has no strike.
        """
        total = ZERO
        for leg in self.legs:
            if leg.is_future():
                entry_price = leg.trade_price()
                if entry_price is None:
                    raise ValueError(f'the future {leg.instrument_id} has no price to measure its payoff from')
                value = underlying_price - entry_price
            else:
                value = self.intrinsic_value(leg, underlying_price)
            total = total + value * leg.units() * leg.direction()
        return total

    def intrinsic_value(self, leg, underlying_price):
        """One unit of an option's value at expiry.

        Args:
            leg (PricedLeg): The option leg.
            underlying_price (decimal.Decimal): Where the underlying finishes.

        Returns:
            decimal.Decimal: The call's amount above the strike or the put's amount below it, never less than zero.

        Raises:
            ValueError: When the option has no strike or its type is neither `CE` nor `PE`.
        """
        strike_price = leg.strike_price()
        if strike_price is None:
            raise ValueError(f'the option {leg.instrument_id} has no strike price')
        if leg.option_type() == 'CE':
            return max(underlying_price - strike_price, ZERO)
        if leg.option_type() == 'PE':
            return max(strike_price - underlying_price, ZERO)
        raise ValueError(f'the option {leg.instrument_id} is neither a call nor a put: {leg.option_type()!r}')

    def slope_above_highest_strike(self):
        """How the payoff changes for each rupee the underlying rises beyond every strike.

        Returns:
            decimal.Decimal: The units of calls and futures bought less those sold; below zero, the loss has no limit.
        """
        slope = ZERO
        for leg in self.legs:
            if leg.is_future() or leg.option_type() == 'CE':
                slope = slope + leg.units() * leg.direction()
        return slope

    def turning_points(self):
        """The underlying prices at which the lowest payoff can occur.

        Returns:
            list: Zero and every strike (decimal.Decimal), in rising order and without repeats.
        """
        prices = [
            ZERO,
        ]
        for leg in self.legs:
            if leg.is_option():
                strike_price = leg.strike_price()
                if strike_price is not None and strike_price not in prices:
                    prices.append(strike_price)
        prices.sort()
        return prices

    def maximum_loss(self):
        """The most the set can lose at expiry, leaving out premiums.

        Returns:
            decimal.Decimal | None: The loss as a positive number, zero when the set cannot lose, or None when the loss has no limit or cannot be worked out.
        """
        if self.slope_above_highest_strike() < 0:
            return None
        try:
            lowest = None
            for underlying_price in self.turning_points():
                payoff = self.payoff_at(underlying_price)
                if lowest is None or payoff < lowest:
                    lowest = payoff
        except ValueError:
            return None
        if lowest is None or lowest >= 0:
            return ZERO
        return -lowest
