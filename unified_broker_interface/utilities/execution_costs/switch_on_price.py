"""The price a position must reach before its breakeven stop is moved to the tripwire."""

import decimal

FALLBACK_EXTRA_TICKS = 2


class SwitchOnPrice:
    """The level beyond the tripwire that the watched price must reach before the stop moves to the tripwire.

    Moving the stop to the tripwire as soon as the price reaches it would let the next ordinary wobble fire it. The switch-on is the tripwire moved further away from the market by the instrument's flicker, the move against the position that the price usually makes within a few seconds, as `PriceFlicker` measures it. Without a measured flicker it is the tripwire plus the live spread and two ticks, like the tripwire's own fallback.

    `price` rounds to the tick away from the tripwire.

    Attributes:
        tripwire (TripwirePrice): The stop's tripwire.
        flicker (decimal.Decimal | None): The measured flicker in price, or None when it is not known.
        spread (decimal.Decimal | None): The live spread, used when the flicker is not known.
    """

    def __init__(self, tripwire, flicker=None, spread=None):
        """Builds the switch-on.

        Args:
            tripwire (TripwirePrice): The stop's tripwire.
            flicker (decimal.Decimal | None): The measured flicker, or None.
            spread (decimal.Decimal | None): The live spread, or None.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When neither a flicker nor a spread is given, or the flicker is below zero.
        """
        if flicker is None and spread is None:
            raise ValueError('A switch-on needs a measured flicker or the live spread.')
        if flicker is not None and decimal.Decimal(flicker) < 0:
            raise ValueError(f'The flicker cannot be below zero: {flicker=}')
        self.tripwire = tripwire
        if flicker is None:
            self.flicker = None
        else:
            self.flicker = decimal.Decimal(flicker)
        if spread is None:
            self.spread = None
        else:
            self.spread = decimal.Decimal(spread)

    def source(self):
        """Which distance the switch-on used.

        Returns:
            str: `measured` when it used the measured flicker, or `spread` when it fell back to the live spread.
        """
        if self.flicker is not None:
            return 'measured'
        return 'spread'

    def distance_from_tripwire(self):
        """How far beyond the tripwire the switch-on is before rounding.

        Returns:
            decimal.Decimal: The flicker, or the spread plus two ticks.
        """
        if self.flicker is not None:
            return self.flicker
        tick_size = self.tripwire.breakeven.tick_size or decimal.Decimal(0)
        return self.spread + FALLBACK_EXTRA_TICKS * tick_size

    def price(self):
        """The switch-on, rounded to the tick away from the tripwire.

        Returns:
            decimal.Decimal: The price, or the unrounded price when the breakeven has no tick size.
        """
        trigger = self.tripwire.price()
        bought = self.tripwire.breakeven.opening_side == 'BUY'
        if bought:
            level = trigger + self.distance_from_tripwire()
        else:
            level = trigger - self.distance_from_tripwire()
        tick_size = self.tripwire.breakeven.tick_size
        if tick_size is None:
            return level
        ticks = level / tick_size
        if bought:
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_CEILING)
        else:
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_FLOOR)
        return whole_ticks * tick_size

    def distance_from_entry(self):
        """How far the switch-on is from the entry price, in the direction the position needs the price to go.

        Returns:
            decimal.Decimal: The rounded switch-on's distance from the entry, per unit.
        """
        if self.tripwire.breakeven.opening_side == 'BUY':
            return self.price() - self.tripwire.breakeven.entry_price
        return self.tripwire.breakeven.entry_price - self.price()
