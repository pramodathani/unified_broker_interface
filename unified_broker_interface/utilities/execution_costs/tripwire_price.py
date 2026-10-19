"""The trigger a protective stop should use so that, after its usual slip, it still closes at or beyond the real breakeven."""

import decimal

FALLBACK_EXTRA_TICKS = 2


class TripwirePrice:
    """The trigger of a breakeven stop: the real breakeven, moved away from the market by the slip such stops show.

    A stop does not sell at its trigger. It fires when the price crosses the trigger and then fills at whatever the next price is, so it lands a little beyond. Setting the trigger at the real breakeven therefore loses that slip. This class moves the trigger above the floor, for a bought position, by enough that a fill slipping by the allowance still lands on the floor:

        trigger × (1 − allowance) = floor

    and below it by the same rule for a sold position. The allowance is a share of the trigger, as `StopSlipAllowance` measures it. When there is no measured allowance, the trigger is instead the floor plus the live spread and two ticks, a cautious guess that needs no history.

    `price` rounds to the tick away from the floor, so the trigger is never closer to it than worked out.

    Attributes:
        breakeven (BreakevenPrice): The position's real breakeven, the floor.
        slip_fraction (decimal.Decimal | None): The allowance as a share of the trigger, or None when it is not known.
        spread (decimal.Decimal | None): The live gap between the best bid and the best offer, used when the allowance is not known.
    """

    def __init__(self, breakeven, slip_fraction=None, spread=None):
        """Builds the tripwire.

        Args:
            breakeven (BreakevenPrice): The position's real breakeven.
            slip_fraction (decimal.Decimal | None): The allowance as a share of the trigger, or None.
            spread (decimal.Decimal | None): The live spread, or None.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When neither an allowance nor a spread is given, or the allowance is not below one.
        """
        if slip_fraction is None and spread is None:
            raise ValueError('A tripwire needs a measured slip allowance or the live spread.')
        if slip_fraction is not None and not 0 <= slip_fraction < 1:
            raise ValueError(f'The slip allowance must be a share from 0 to below 1: {slip_fraction=}')
        self.breakeven = breakeven
        if slip_fraction is None:
            self.slip_fraction = None
        else:
            self.slip_fraction = decimal.Decimal(slip_fraction)
        if spread is None:
            self.spread = None
        else:
            self.spread = decimal.Decimal(spread)

    def source(self):
        """Which allowance the tripwire used.

        Returns:
            str: `measured` when it used the measured slip, or `spread` when it fell back to the live spread.
        """
        if self.slip_fraction is not None:
            return 'measured'
        return 'spread'

    def exact_price(self):
        """The trigger before rounding to a tick.

        Returns:
            decimal.Decimal: The trigger, to four decimal places, rounded away from the floor.
        """
        floor = self.breakeven.price()
        bought = self.breakeven.opening_side == 'BUY'
        if self.slip_fraction is not None:
            if bought:
                trigger = floor / (1 - self.slip_fraction)
            else:
                trigger = floor / (1 + self.slip_fraction)
        else:
            tick_size = self.breakeven.tick_size or decimal.Decimal(0)
            distance = self.spread + FALLBACK_EXTRA_TICKS * tick_size
            if bought:
                trigger = floor + distance
            else:
                trigger = floor - distance
        places = decimal.Decimal('0.0001')
        if bought:
            return trigger.quantize(places, rounding=decimal.ROUND_CEILING)
        return trigger.quantize(places, rounding=decimal.ROUND_FLOOR)

    def price(self):
        """The trigger, rounded to the tick away from the floor.

        Returns:
            decimal.Decimal: The trigger price, or the exact price when the breakeven has no tick size.
        """
        exact = self.exact_price()
        tick_size = self.breakeven.tick_size
        if tick_size is None:
            return exact
        ticks = exact / tick_size
        if self.breakeven.opening_side == 'BUY':
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_CEILING)
        else:
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_FLOOR)
        return whole_ticks * tick_size

    def distance_from_floor(self):
        """How far the trigger is beyond the floor, away from the market's adverse direction.

        Returns:
            decimal.Decimal: The rounded trigger's distance from the rounded floor, per unit.
        """
        if self.breakeven.opening_side == 'BUY':
            return self.price() - self.breakeven.price()
        return self.breakeven.price() - self.price()

    def distance_from_entry(self):
        """How far the trigger is from the entry price, in the direction the position needs the price to go.

        Returns:
            decimal.Decimal: The rounded trigger's distance from the entry, per unit.
        """
        if self.breakeven.opening_side == 'BUY':
            return self.price() - self.breakeven.entry_price
        return self.breakeven.entry_price - self.price()
