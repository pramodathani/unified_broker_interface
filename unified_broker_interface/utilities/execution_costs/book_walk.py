"""How an order would fill against the visible levels of one side of an order book."""


class BookWalk:
    """An order's quantity laid against the price levels it would trade with, best level first.

    A buy walks the asks and a sell walks the bids. Each level fills as much of what is left as it holds, so the walk says how much the visible book covers, at what average price, and how much is left over beyond the last visible level.

    Attributes:
        quantity (int): The order's quantity, in units.
        levels (list): The levels it trades with, as tuples of price (decimal.Decimal) and quantity (int), best first; levels with no price or no quantity are left out.
    """

    def __init__(self, quantity, levels):
        """Builds the walk.

        Args:
            quantity (int): The order's quantity, in units.
            levels (list): Tuples of price (decimal.Decimal | None) and quantity (int | None), best first.

        Returns:
            None: This method returns nothing.
        """
        self.quantity = quantity
        self.levels = []
        for price, level_quantity in levels:
            if price is None or price <= 0:
                continue
            if level_quantity is None or level_quantity <= 0:
                continue
            self.levels.append((price, level_quantity))

    def visible_quantity(self):
        """The quantity the visible levels hold altogether.

        Returns:
            int: Units.
        """
        total = 0
        for price, level_quantity in self.levels:
            total = total + level_quantity
        return total

    def filled_quantity(self):
        """How much of the order the visible levels fill.

        Returns:
            int: Units, never more than the order's quantity.
        """
        return min(self.quantity, self.visible_quantity())

    def remaining_quantity(self):
        """How much of the order is left beyond the last visible level.

        Returns:
            int: Units.
        """
        return self.quantity - self.filled_quantity()

    def levels_used(self):
        """How many levels the order reaches, counting a level it only partly takes.

        Returns:
            int: The number of levels.
        """
        left = self.quantity
        used = 0
        for price, level_quantity in self.levels:
            if left <= 0:
                break
            used = used + 1
            left = left - level_quantity
        return used

    def average_price(self):
        """The average price of the part the visible levels fill.

        Returns:
            decimal.Decimal | None: The price, or None when nothing is visible or the quantity is zero.
        """
        left = self.quantity
        spent = 0
        taken = 0
        for price, level_quantity in self.levels:
            if left <= 0:
                break
            take = min(left, level_quantity)
            spent = spent + price * take
            taken = taken + take
            left = left - take
        if taken == 0:
            return None
        return spent / taken

    def worst_price(self):
        """The price of the last level the order reaches, or the last visible level when the order goes beyond it.

        Returns:
            decimal.Decimal | None: The price, or None when nothing is visible.
        """
        used = self.levels_used()
        if used == 0:
            return None
        return self.levels[used - 1][0]
