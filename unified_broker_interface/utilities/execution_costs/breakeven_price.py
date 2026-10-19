"""The exit price at which a trade makes exactly nothing once every tax, fee and brokerage is paid."""

import decimal

PRICE_PLACES = decimal.Decimal('0.0001')


class BreakevenPrice:
    """The real breakeven of one position: the exit price that leaves a profit of zero after every charge.

    For a position opened by buying, the exit is a sell, and selling at S breaks even when

        S × quantity × (1 − sell-side rate) = entry × quantity × (1 + buy-side rate) + brokerage × (1 + GST)

    where the rates come from the segment's `ChargeRate` and the brokerage is for both orders. A position opened by selling mirrors it: the exit is a buy, and the breakeven is the highest buy-back price that still leaves nothing lost. Flat brokerage is shared across the quantity, so a small quantity has a breakeven further from its entry.

    `price` rounds to the tick on the safe side: up for a bought position and down for a sold one, so an exit at that price never loses.

    Attributes:
        charge_rate (ChargeRate): The segment's statutory rates.
        opening_side (str): `BUY` for a position opened by buying, or `SELL` for one opened by selling.
        entry_price (decimal.Decimal): The average price the position was opened at.
        quantity (int): The position's size, in units.
        brokerage_per_order (decimal.Decimal): The brokerage for one order, before GST.
        tick_size (decimal.Decimal | None): The instrument's tick size, or None to leave the price unrounded.
    """

    def __init__(
        self,
        charge_rate,
        opening_side,
        entry_price,
        quantity,
        brokerage_per_order=decimal.Decimal(0),
        tick_size=None,
    ):
        """Builds the breakeven.

        Args:
            charge_rate (ChargeRate): The segment's statutory rates.
            opening_side (str): `BUY` or `SELL`, the side of the order that opened the position.
            entry_price (decimal.Decimal): The average opening price.
            quantity (int): The position's size, in units.
            brokerage_per_order (decimal.Decimal): The brokerage for one order, before GST.
            tick_size (decimal.Decimal | None): The tick size, or None.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the opening side is neither `BUY` nor `SELL`, or the quantity is not positive.
        """
        if opening_side not in ('BUY', 'SELL'):
            raise ValueError(f'The opening side must be BUY or SELL: {opening_side=}')
        if quantity <= 0:
            raise ValueError(f'The quantity must be positive: {quantity=}')
        self.charge_rate = charge_rate
        self.opening_side = opening_side
        self.entry_price = decimal.Decimal(entry_price)
        self.quantity = quantity
        self.brokerage_per_order = decimal.Decimal(brokerage_per_order)
        if tick_size is None:
            self.tick_size = None
        else:
            self.tick_size = decimal.Decimal(tick_size)

    def brokerage_with_gst(self):
        """The brokerage for the opening and the closing order, with GST on it.

        Returns:
            decimal.Decimal: The rupees, for both orders together.
        """
        return 2 * self.brokerage_per_order * (1 + self.charge_rate.gst_rate)

    def exact_price(self):
        """The breakeven before rounding to a tick.

        Returns:
            decimal.Decimal: The exit price, to four decimal places.
        """
        buy_side = 1 + self.charge_rate.buy_side_rate()
        sell_side = 1 - self.charge_rate.sell_side_rate()
        entry_value = self.entry_price * self.quantity
        if self.opening_side == 'BUY':
            needed = entry_value * buy_side + self.brokerage_with_gst()
            price = needed / (self.quantity * sell_side)
            return price.quantize(PRICE_PLACES, rounding=decimal.ROUND_CEILING)
        kept = entry_value * sell_side - self.brokerage_with_gst()
        price = kept / (self.quantity * buy_side)
        return price.quantize(PRICE_PLACES, rounding=decimal.ROUND_FLOOR)

    def price(self):
        """The breakeven, rounded to the tick on the side that never loses.

        Returns:
            decimal.Decimal: The exit price: rounded up for a bought position and down for a sold one, or the exact price when there is no tick size.
        """
        exact = self.exact_price()
        if self.tick_size is None:
            return exact
        ticks = exact / self.tick_size
        if self.opening_side == 'BUY':
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_CEILING)
        else:
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_FLOOR)
        return whole_ticks * self.tick_size

    def distance(self):
        """How far the breakeven is from the entry, in the direction the position needs the price to go.

        Returns:
            decimal.Decimal: The rounded breakeven's distance from the entry price, per unit.
        """
        if self.opening_side == 'BUY':
            return self.price() - self.entry_price
        return self.entry_price - self.price()
