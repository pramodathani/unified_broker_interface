"""One instrument's live quote, read as the prices an order type watching the market needs."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)


class MarketView:
    """The best bid, the best offer, the last trade and the midpoint, out of one quote.

    This is the tick-by-tick cousin of `PriceReference`, and the difference between them is what they do when the quote does not carry what was asked for. `PriceReference` is answering a caller who is waiting on an HTTP request, so a missing price is a refusal with a status code. This is answering a tick, where the honest response to a missing price is to do nothing and look again in a second. So every reader here returns None instead of raising, and a type that cannot act without a price simply returns False for that tick.

    Prices read out of the book are snapped to the nearest tick on the way out, for the reason set out at length in `PriceReference.number`: a quote is built from JSON floats, so an offer of 1000.10 arrives as 1000.0999999999999, and rounding that towards the passive side moves it a whole tick and lands on the wrong level of the book. The midpoint is deliberately not snapped, because it belongs between two ticks and which way it goes is the caller's decision.

    Attributes:
        quote (dict | None): The instrument's entry in `unified:quotes:live`.
        tick_size (decimal.Decimal | None): The instrument's tick size.
        rounder (OrderRequest): Where the rounding lives.
    """

    def __init__(self, quote, tick_size):
        """Builds the view.

        Args:
            quote (dict | None): The instrument's live quote, or None when there is none.
            tick_size (decimal.Decimal | None): The instrument's tick size, or None when it is not known.

        Returns:
            None: This method returns nothing.
        """
        self.quote = quote if isinstance(quote, dict) else None
        self.tick_size = tick_size
        self.rounder = OrderRequest()

    def is_readable(self):
        """Whether there is a quote and a tick size to work with at all.

        Returns:
            bool: True when a price can be asked for.
        """
        return self.quote is not None and self.tick_size is not None

    def is_stale(self):
        """Whether the quote is marked stale, because the broker that owned it went silent with no healthy backup.

        Returns:
            bool: True when the quote should not be acted on.
        """
        if self.quote is None:
            return False
        return self.quote.get('stale') is True

    def number(self, value):
        """One value out of the quote, as a price above zero snapped to the tick.

        Args:
            value (object): The field's value.

        Returns:
            decimal.Decimal | None: The price, or None when the field is missing or unusable.
        """
        if value is None or self.tick_size is None:
            return None
        try:
            price = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not price.is_finite() or price <= 0:
            return None
        return self.rounder.rounded_to_tick(price, self.tick_size)

    def last(self):
        """The last traded price.

        Returns:
            decimal.Decimal | None: The price, or None when the quote does not carry one.
        """
        if not self.is_readable():
            return None
        return self.number(self.quote.get('last_price'))

    def level(self, side, level):
        """One level of one side of the depth.

        Args:
            side (str): `buy` or `sell`, as the depth names them.
            level (int): The level, counting the touch as 1.

        Returns:
            decimal.Decimal | None: The price at that level, or None when the book does not reach it.
        """
        if not self.is_readable():
            return None
        depth = self.quote.get('depth')
        if not isinstance(depth, dict):
            return None
        levels = depth.get(side)
        if not isinstance(levels, list) or len(levels) < level:
            return None
        entry = levels[level - 1]
        if not isinstance(entry, dict):
            return None
        return self.number(entry.get('price'))

    def best_bid(self):
        """The highest price anybody is bidding.

        Returns:
            decimal.Decimal | None: The price, or None when the book has no bid.
        """
        return self.level('buy', 1)

    def best_offer(self):
        """The lowest price anybody is offering.

        Returns:
            decimal.Decimal | None: The price, or None when the book has no offer.
        """
        return self.level('sell', 1)

    def mid(self):
        """The midpoint of the touch, which is usually between two ticks.

        Returns:
            decimal.Decimal | None: The midpoint, unrounded, or None when either side is missing.
        """
        bid = self.best_bid()
        offer = self.best_offer()
        if bid is None or offer is None:
            return None
        return (bid + offer) / 2

    def own_touch(self, transaction_type):
        """The best price on the side an order of this side would join.

        A buy joins the bid, because that is where buyers rest. An order placed here takes nothing and waits.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when that side of the book is empty.
        """
        if transaction_type == 'BUY':
            return self.best_bid()
        return self.best_offer()

    def opposite_touch(self, transaction_type):
        """The best price on the side an order of this side has to reach to fill now.

        A buy has to reach the offer. An order placed here takes liquidity and fills immediately, up to whatever that level holds.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when that side of the book is empty.
        """
        if transaction_type == 'BUY':
            return self.best_offer()
        return self.best_bid()

    def rounded(self, price, towards_passive=None):
        """One computed price, brought to a tick boundary.

        Args:
            price (decimal.Decimal): The price to round.
            towards_passive (str | None): BUY to round down and SELL to round up, or None for the nearest tick.

        Returns:
            decimal.Decimal | None: The rounded price, or None when the tick size is not known.
        """
        if self.tick_size is None:
            return None
        return self.rounder.rounded_to_tick(
            price,
            self.tick_size,
            towards_passive,
        )

    def moved(self, price, ticks, transaction_type, towards_market):
        """One price moved a whole number of ticks, in the direction a side treats as aggressive or passive.

        A buy gets more aggressive by going up and a sell by going down, so the sign depends on both the side and which way the caller meant.

        Args:
            price (decimal.Decimal): The price to move.
            ticks (int): How many ticks to move it.
            transaction_type (str): BUY or SELL.
            towards_market (bool): True to move towards filling, False to move away from it.

        Returns:
            decimal.Decimal | None: The moved price, or None when the tick size is not known.
        """
        if self.tick_size is None:
            return None
        upwards = transaction_type == 'BUY'
        if not towards_market:
            upwards = not upwards
        step = self.tick_size * ticks
        return price + step if upwards else price - step
