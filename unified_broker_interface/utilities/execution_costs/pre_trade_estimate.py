"""What an order would cost to fill right now by crossing the spread, worked out before it is sent."""

import decimal

from unified_broker_interface.utilities.execution_costs.book_walk import (
    BookWalk,
)

TWO = decimal.Decimal(2)
BASIS_POINTS = decimal.Decimal(10000)
PRICE_PLACES = decimal.Decimal('0.0001')
BASIS_POINT_PLACES = decimal.Decimal('0.01')
RUPEE_PLACES = decimal.Decimal('0.01')


class PreTradeEstimate:
    """The expected cost of filling a whole order now against the visible book, with the square-root model for anything beyond it.

    The cost is measured against the mid-price, per unit of the whole order, and split into three parts that add up to the total:

    - `half_spread`: from the mid-price to the best price on the other side.
    - `book_walk`: from that best price to the average of the visible levels the order takes, with any quantity beyond the last visible level counted at that level's price.
    - `beyond_book`: what the square-root model adds for that left-over quantity: coefficient × daily volatility × mid-price × √(left-over ÷ average daily volume), spread over the whole order.

    The first two parts are exact for the book as it stands. The third is a model, and is None when the order needs it but the volatility, volume or coefficient is missing; the total is then None too. An empty other side leaves everything None.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        quantity (int): The order's quantity, in units.
        bids (list): The bid levels, as tuples of price and quantity, best first.
        asks (list): The ask levels, in the same form.
        liquidity (DailyLiquidity | None): The instrument's daily volatility and volume.
        coefficient (decimal.Decimal | None): The square-root model's coefficient.
        walk (BookWalk): The order laid against the other side of the book.
    """

    def __init__(self, transaction_type, quantity, bids, asks, liquidity=None, coefficient=None):
        """Builds the estimate.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            quantity (int): The order's quantity, in units.
            bids (list): Tuples of price (decimal.Decimal) and quantity (int), best first.
            asks (list): Tuples of price (decimal.Decimal) and quantity (int), best first.
            liquidity (DailyLiquidity | None): The instrument's daily volatility and volume, or None when not known.
            coefficient (decimal.Decimal | None): The square-root model's coefficient, or None when not known.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.quantity = quantity
        self.bids = BookWalk(0, bids).levels
        self.asks = BookWalk(0, asks).levels
        self.liquidity = liquidity
        self.coefficient = coefficient
        if transaction_type == 'SELL':
            self.walk = BookWalk(quantity, self.bids)
        else:
            self.walk = BookWalk(quantity, self.asks)

    def side(self):
        """The sign that turns a price above the mid-price into a cost.

        Returns:
            int: 1 for a buy and -1 for a sell.
        """
        if self.transaction_type == 'SELL':
            return -1
        return 1

    def is_priceable(self):
        """Whether both sides of the book have a price, so there is a mid-price to measure from.

        Returns:
            bool: True when there is a best bid and a best ask and the quantity is positive.
        """
        return bool(self.bids) and bool(self.asks) and self.quantity > 0

    def is_covered_by_book(self):
        """Whether the visible levels hold the whole order, so no model is needed.

        Returns:
            bool: True when nothing is left beyond the last visible level.
        """
        return self.walk.remaining_quantity() == 0

    def mid(self):
        """The mid-price of the book.

        Returns:
            decimal.Decimal | None: The mid-price, or None when the book cannot be priced.
        """
        if not self.is_priceable():
            return None
        return (self.bids[0][0] + self.asks[0][0]) / TWO

    def touch(self):
        """The best price on the side the order trades with.

        Returns:
            decimal.Decimal | None: The best ask for a buy and the best bid for a sell, or None when the book cannot be priced.
        """
        if not self.is_priceable():
            return None
        return self.walk.levels[0][0]

    def half_spread(self):
        """The cost of crossing from the mid-price to the best price on the other side.

        Returns:
            decimal.Decimal | None: Per unit, rounded to four places, or None when the book cannot be priced.
        """
        if not self.is_priceable():
            return None
        return self.rounded(self.side() * (self.touch() - self.mid()))

    def book_walk(self):
        """The cost of taking the visible levels beyond the best one, with any left-over quantity counted at the last visible level's price.

        Returns:
            decimal.Decimal | None: Per unit of the whole order, rounded to four places, or None when the book cannot be priced.
        """
        if not self.is_priceable():
            return None
        filled = self.walk.filled_quantity()
        remaining = self.walk.remaining_quantity()
        total = self.walk.average_price() * filled + self.walk.worst_price() * remaining
        average = total / self.quantity
        return self.rounded(self.side() * (average - self.touch()))

    def remainder_impact(self):
        """How far the square-root model expects the left-over quantity to move the price, per unit of that quantity.

        Returns:
            decimal.Decimal | None: Zero when the visible book covers the order, the model's figure rounded to four places otherwise, or None when it is needed and cannot be worked out.
        """
        remaining = self.walk.remaining_quantity()
        if remaining == 0:
            return decimal.Decimal(0)
        if self.liquidity is None or self.coefficient is None or self.mid() is None:
            return None
        volatility = self.liquidity.volatility()
        average_volume = self.liquidity.average_volume()
        if volatility is None or average_volume is None:
            return None
        share = (decimal.Decimal(remaining) / average_volume).sqrt()
        return self.rounded(self.coefficient * volatility * self.mid() * share)

    def beyond_book(self):
        """The square-root model's cost for the left-over quantity, spread over the whole order.

        Returns:
            decimal.Decimal | None: Per unit of the whole order, rounded to four places, or None when it is needed and cannot be worked out.
        """
        if not self.is_priceable():
            return None
        impact = self.remainder_impact()
        if impact is None:
            return None
        return self.rounded(impact * self.walk.remaining_quantity() / self.quantity)

    def total(self):
        """The whole expected cost against the mid-price: the sum of the three rounded parts, so the parts always add up to it.

        Returns:
            decimal.Decimal | None: Per unit, or None when any part is missing.
        """
        half_spread = self.half_spread()
        book_walk = self.book_walk()
        beyond_book = self.beyond_book()
        if half_spread is None or book_walk is None or beyond_book is None:
            return None
        return half_spread + book_walk + beyond_book

    def average_price(self):
        """The expected average fill price of the whole order.

        Returns:
            decimal.Decimal | None: The price, rounded to four places, or None when the total is missing.
        """
        total = self.total()
        if total is None:
            return None
        return (self.mid() + self.side() * total).quantize(PRICE_PLACES)

    def basis_points(self):
        """The whole expected cost as a share of the mid-price.

        Returns:
            decimal.Decimal | None: Basis points, rounded to a hundredth, or None when the total is missing.
        """
        total = self.total()
        if total is None:
            return None
        return (total / self.mid() * BASIS_POINTS).quantize(BASIS_POINT_PLACES)

    def rupees(self):
        """The whole expected cost of the order.

        Returns:
            decimal.Decimal | None: Rupees, rounded to the paisa, or None when the total is missing.
        """
        total = self.total()
        if total is None:
            return None
        return (total * self.quantity).quantize(RUPEE_PLACES)

    def rounded(self, value):
        """A per-unit figure rounded to four places, with the minus sign taken off a zero.

        Args:
            value (decimal.Decimal): The figure.

        Returns:
            decimal.Decimal: The rounded figure.
        """
        result = decimal.Decimal(value).quantize(PRICE_PLACES)
        if result == 0:
            return abs(result)
        return result
