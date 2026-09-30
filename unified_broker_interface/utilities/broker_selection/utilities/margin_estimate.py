"""A cautious estimate of the exchange margin an order, or a strategy of several legs, needs, worked out without calling a broker."""

import decimal

from unified_broker_interface.utilities.broker_selection.utilities.option_payoff import (
    OptionPayoff,
)

ZERO = decimal.Decimal(0)
FULL_VALUE = decimal.Decimal(1)


class MarginEstimate:
    """Works out the margin the exchange blocks for an order, from the margin rate table and the prices Redis holds.

    Each kind of order has its own rule. A delivery buy needs its whole value and a delivery sell needs nothing, because the broker checks holdings instead of cash. An intraday order needs its value times the segment's VaR rate. A future needs its value times SPAN plus exposure. A bought option needs its premium. A sold option needs its underlying's value times SPAN plus exposure, which the brokers' own calculators showed on 2026-09-30 is never less than they ask. A segment with no rate is charged the whole value.

    A strategy is sent one leg at a time and the broker checks each leg as it arrives, so the estimate for several legs is the highest requirement reached along the way, not the requirement once they are all in. Without hedge benefit every leg is added up on its own. With it, a set of options and futures on one underlying and expiry is charged its most possible loss at expiry, plus exposure on every sold option and future, plus the premium paid for every bought option, whenever that is less than the legs added up.

    The estimate is the exchange's margin. A broker's own surcharge is applied afterwards, by whoever knows which broker is asking.

    Attributes:
        margin_rate_table (MarginRateTable): The exchange's rates.
    """

    def __init__(self, margin_rate_table):
        """Builds the estimate.

        Args:
            margin_rate_table (MarginRateTable): The exchange's rates.

        Returns:
            None: This method returns nothing.
        """
        self.margin_rate_table = margin_rate_table

    def margin_category(self, leg):
        """Which of a broker's margin multipliers applies to a leg.

        Args:
            leg (PricedLeg): The leg.

        Returns:
            str: `commodity` for a commodity derivative, `fno` for any other derivative, `delivery` for a delivery order and `intraday` for any other equity order.
        """
        if leg.market_category() == 'commodity':
            return 'commodity'
        if leg.is_option() or leg.is_future():
            return 'fno'
        if leg.order.product == 'CNC':
            return 'delivery'
        return 'intraday'

    def total_rate(self, leg):
        """The share of a leg's value the exchange blocks, SPAN or VaR plus exposure.

        Args:
            leg (PricedLeg): The leg.

        Returns:
            decimal.Decimal: The rate, or 1 when the table has no row for the leg's segment.
        """
        margin_rate = self.margin_rate_table.rate(leg.segment(), leg.underlying_symbol())
        if margin_rate is None:
            return FULL_VALUE
        return decimal.Decimal(margin_rate.total_rate())

    def exposure_rate(self, leg):
        """The exposure margin's share of a leg's value.

        Args:
            leg (PricedLeg): The leg.

        Returns:
            decimal.Decimal: The rate, or 1 when the table has no row for the leg's segment.
        """
        margin_rate = self.margin_rate_table.rate(leg.segment(), leg.underlying_symbol())
        if margin_rate is None:
            return FULL_VALUE
        return decimal.Decimal(margin_rate.exposure_rate)

    def leg_margin(self, leg):
        """The margin one leg needs on its own.

        Args:
            leg (PricedLeg): The leg.

        Returns:
            decimal.Decimal | None: The margin, or None when a price it needs is not known.
        """
        price = leg.trade_price()
        if leg.is_option():
            if leg.is_buy():
                if price is None:
                    return None
                return price * leg.units()
            if leg.underlying_price is None:
                return None
            return leg.underlying_price * leg.units() * self.total_rate(leg)
        if price is None:
            return None
        value = price * leg.units()
        if leg.is_future():
            return value * self.total_rate(leg)
        if leg.order.product == 'MIS':
            return value * self.total_rate(leg)
        if leg.is_buy():
            return value
        return ZERO

    def legs_margin(self, legs):
        """The margin several legs need when each stands alone, added up.

        Args:
            legs (list): The `PricedLeg` legs.

        Returns:
            decimal.Decimal | None: The sum, or None when any leg's margin is not known.
        """
        total = ZERO
        for leg in legs:
            margin = self.leg_margin(leg)
            if margin is None:
                return None
            total = total + margin
        return total

    def can_be_hedged(self, legs):
        """Whether a set of legs is options and futures on one underlying with one expiry, which is what hedge benefit applies to.

        Args:
            legs (list): The `PricedLeg` legs.

        Returns:
            bool: True when every leg is an option or future sharing the first leg's underlying and expiry, and there are at least two legs.
        """
        if len(legs) < 2:
            return False
        first = legs[0]
        for leg in legs:
            if not leg.is_option() and not leg.is_future():
                return False
            if leg.underlying_symbol() != first.underlying_symbol():
                return False
            if leg.expiry_date() != first.expiry_date():
                return False
        return True

    def hedged_margin(self, legs):
        """The margin a hedged set of options and futures needs: its most possible loss, plus exposure, plus premiums paid.

        Args:
            legs (list): The `PricedLeg` legs, which `can_be_hedged` has accepted.

        Returns:
            decimal.Decimal | None: The margin, or None when the loss has no limit or a price it needs is not known.
        """
        maximum_loss = OptionPayoff(legs).maximum_loss()
        if maximum_loss is None:
            return None
        total = maximum_loss
        for leg in legs:
            if leg.is_future():
                price = leg.trade_price()
                if price is None:
                    return None
                total = total + price * leg.units() * self.exposure_rate(leg)
            elif leg.is_buy():
                premium = leg.trade_price()
                if premium is None:
                    return None
                total = total + premium * leg.units()
            else:
                if leg.underlying_price is None:
                    return None
                total = total + leg.underlying_price * leg.units() * self.exposure_rate(leg)
        return total

    def settled_margin(self, legs, hedge_benefit):
        """The margin a set of legs needs once every one of them has been sent.

        Args:
            legs (list): The `PricedLeg` legs.
            hedge_benefit (bool): Whether the broker prices hedged legs together.

        Returns:
            decimal.Decimal | None: The margin, or None when it cannot be worked out.
        """
        standalone = self.legs_margin(legs)
        if not hedge_benefit or not self.can_be_hedged(legs):
            return standalone
        hedged = self.hedged_margin(legs)
        if hedged is None:
            return standalone
        if standalone is None or hedged < standalone:
            return hedged
        return standalone

    def required(self, legs, hedge_benefit):
        """The highest margin reached while the legs are sent one after another.

        Args:
            legs (list): The `PricedLeg` legs, in send order.
            hedge_benefit (bool): Whether the broker prices hedged legs together.

        Returns:
            decimal.Decimal | None: The highest requirement, or None when it cannot be worked out for some point along the way.
        """
        highest = ZERO
        for count in range(1, len(legs) + 1):
            margin = self.settled_margin(legs[:count], hedge_benefit)
            if margin is None:
                return None
            if margin > highest:
                highest = margin
        return highest
