"""Where one held limit order would be standing in the exchange's queue, worked out from the quotes that go past."""

import decimal

PRICE_PLACES = decimal.Decimal('0.0001')
VISIBLE_LEVELS = 5
OWN_SIDES = {
    'BUY': 'buy',
    'SELL': 'sell',
}
OPPOSITE_SIDES = {
    'BUY': 'sell',
    'SELL': 'buy',
}


class VirtualQueue:
    """One held limit order's estimated place in the queue at its price, as if it had been resting at the exchange all along.

    The exchange fills orders at one price in the order they arrived. So an order resting at 98 behind 12,000 already bid there is filled only once 12,000 have traded at 98, or once those ahead of it have cancelled. This follows that, quote by quote, from what a quote shows: the visible quantity at the price, the day's volume, and the last traded price.

    Three things move the estimate:

    1. **Trades at the price.** When the last trade was at the order's price, the rise in volume since the last quote is taken to have traded there, and it serves the queue ahead of the order first. Whatever is left over after the queue is gone fills the order.
    2. **Trades through the price.** When the last trade was on the far side of the price, lower for a buy, every bid at the price must have been used up first, so the whole order would have filled.
    3. **Cancellations.** When the visible quantity at the price falls by more than traded there, the difference cancelled. Nobody can see whether those orders were ahead or behind, so the share ahead shrinks in proportion to how much of the level was ahead.

    The opposite touch reaching the price is the fourth event, and it is kept apart from the others. That is the moment the order engine sends the real order, which then fills straight away, so it is not a fill the queue would have given. `queue_filled` counts only what the queue gave; `filled` is that plus, once `touched_at` is set, the rest of the order. For a real order, `queue_filled` at the moment it is sent is what holding it back cost: fills a resting order would have had and this one did not.

    Attributes:
        parent_order_id (str): The parent this estimate belongs to.
        instrument_id (str): The instrument.
        side (str): BUY or SELL.
        price (decimal.Decimal): The order's limit price.
        quantity (int): The order's quantity, in units.
        ahead (int | None): The quantity estimated to be ahead of the order, or None while the price is outside the visible depth.
        queue_filled (int): How much the queue would have filled so far.
        touched_at (float | None): When the opposite touch first reached the price, as epoch seconds, or None.
        last_volume (int | None): The day's volume on the last quote used.
        last_broker (str | None): Which broker owned the last quote used.
        last_visible (int | None): The visible quantity at the price on the last quote used.
        needs_baseline (bool): Whether the next quote only sets the baseline rather than being compared with the last one.
        updated_at (float | None): When the last quote used was received, as epoch seconds.
        updates (int): How many quotes have moved the estimate.
    """

    def __init__(self, parent_order_id, instrument_id, side, price, quantity):
        """Builds an estimate that has not seen a quote yet.

        Args:
            parent_order_id (str): The parent.
            instrument_id (str): The instrument.
            side (str): BUY or SELL.
            price (decimal.Decimal): The limit price.
            quantity (int): The quantity, in units.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the side is not BUY or SELL, or the quantity is not above zero.
        """
        if side not in OWN_SIDES:
            raise ValueError(f'A virtual queue needs a side of BUY or SELL: {side=}')
        if quantity <= 0:
            raise ValueError(f'A virtual queue needs a quantity above zero: {quantity=}')
        self.parent_order_id = parent_order_id
        self.instrument_id = instrument_id
        self.side = side
        self.price = self.as_price(price)
        self.quantity = quantity
        self.ahead = None
        self.queue_filled = 0
        self.touched_at = None
        self.last_volume = None
        self.last_broker = None
        self.last_visible = None
        self.needs_baseline = True
        self.updated_at = None
        self.updates = 0

    @classmethod
    def from_document(cls, document):
        """Rebuilds an estimate from what `document` wrote.

        The rebuilt estimate always takes its next quote as a new baseline, because the quotes it missed while nothing was reading them cannot be told apart from trades.

        Args:
            document (dict): The stored estimate.

        Returns:
            VirtualQueue: The estimate.

        Raises:
            ValueError: When the document is missing a field or holds an impossible value.
        """
        try:
            estimate = cls(
                document['parent_order_id'],
                document['instrument_id'],
                document['side'],
                decimal.Decimal(str(document['price'])),
                int(document['quantity']),
            )
            estimate.ahead = document.get('ahead')
            estimate.queue_filled = int(document.get('queue_filled') or 0)
            estimate.touched_at = document.get('touched_at')
            estimate.last_volume = document.get('last_volume')
            estimate.last_broker = document.get('last_broker')
            estimate.last_visible = document.get('last_visible')
            estimate.updated_at = document.get('updated_at')
            estimate.updates = int(document.get('updates') or 0)
        except (KeyError, TypeError, decimal.InvalidOperation) as error:
            raise ValueError(f'Not a stored virtual queue: {error!r}') from error
        estimate.needs_baseline = True
        return estimate

    def document(self):
        """The estimate as a JSON-ready dictionary, for `unified:orders:virtual_queue`.

        Returns:
            dict: The estimate, with `filled` and `remaining` worked out for a reader that only wants those.
        """
        return {
            'parent_order_id': self.parent_order_id,
            'instrument_id': self.instrument_id,
            'side': self.side,
            'price': str(self.price),
            'quantity': self.quantity,
            'ahead': self.ahead,
            'queue_filled': self.queue_filled,
            'filled': self.filled(),
            'remaining': self.quantity - self.filled(),
            'touched_at': self.touched_at,
            'last_volume': self.last_volume,
            'last_broker': self.last_broker,
            'last_visible': self.last_visible,
            'updated_at': self.updated_at,
            'updates': self.updates,
        }

    def as_price(self, value):
        """One price as a decimal with a fixed number of places, so that 98 and 98.0 compare equal.

        Args:
            value (object): The price, as a number, a string or a decimal.

        Returns:
            decimal.Decimal | None: The price, or None when it is missing or not a number.
        """
        if value is None:
            return None
        try:
            price = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not price.is_finite():
            return None
        return price.quantize(PRICE_PLACES)

    def as_quantity(self, value):
        """One quantity as a whole number.

        Args:
            value (object): The quantity.

        Returns:
            int | None: The quantity, or None when it is missing or not a number.
        """
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def filled(self):
        """How much of the order would have filled, counting the opposite touch reaching the price as a fill of the rest.

        Returns:
            int: The quantity.
        """
        if self.touched_at is not None:
            return self.quantity
        return self.queue_filled

    def remaining(self):
        """How much of the order the queue has not filled yet.

        Returns:
            int: The quantity.
        """
        return self.quantity - self.queue_filled

    def levels(self, quote, depth_side):
        """One side of a quote's depth, as (price, quantity) pairs, best first.

        Args:
            quote (dict): The unified quote.
            depth_side (str): `buy` or `sell`.

        Returns:
            list: The (decimal.Decimal, int) pairs that could be read.
        """
        depth = quote.get('depth')
        if not isinstance(depth, dict):
            return []
        entries = depth.get(depth_side)
        if not isinstance(entries, list):
            return []
        levels = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            price = self.as_price(entry.get('price'))
            quantity = self.as_quantity(entry.get('quantity'))
            if price is None or quantity is None:
                continue
            levels.append((price, quantity))
        return levels

    def is_better(self, first, second):
        """Whether one price is better than another for this order's side of the book.

        Args:
            first (decimal.Decimal): One price.
            second (decimal.Decimal): The other.

        Returns:
            bool: True when `first` is higher for a buy, or lower for a sell.
        """
        if self.side == 'BUY':
            return first > second
        return first < second

    def visible_at_price(self, quote):
        """How much is resting at the order's price on its own side of the book.

        Returns zero when the price is better than the best level shown, since the order would then be alone at a new best price, and zero when the price falls between two levels shown, since nobody is there. Returns None only when the book shows all five levels and the price is beyond the last, where whatever is resting cannot be seen.

        Args:
            quote (dict): The unified quote.

        Returns:
            int | None: The quantity, or None when it cannot be seen.
        """
        levels = self.levels(quote, OWN_SIDES[self.side])
        if not levels:
            return None
        for price, quantity in levels:
            if price == self.price:
                return quantity
        worst_price, _ = levels[-1]
        book_is_full = len(levels) >= VISIBLE_LEVELS
        if book_is_full and self.is_better(worst_price, self.price):
            return None
        return 0

    def opposite_touch(self, quote):
        """The best price on the other side of the book: the offer for a buy, the bid for a sell.

        Args:
            quote (dict): The unified quote.

        Returns:
            decimal.Decimal | None: The price, or None when that side is empty.
        """
        levels = self.levels(quote, OPPOSITE_SIDES[self.side])
        if not levels:
            return None
        price, _ = levels[0]
        return price

    def is_touched(self, quote):
        """Whether the other side of the book has reached the order's price, so a limit sent now would fill.

        Args:
            quote (dict): The unified quote.

        Returns:
            bool: True when the offer is at or below a buy's price, or the bid at or above a sell's.
        """
        touch = self.opposite_touch(quote)
        if touch is None:
            return False
        if self.side == 'BUY':
            return touch <= self.price
        return touch >= self.price

    def traded_through(self, last_price):
        """Whether a trade happened on the far side of the order's price, which it could only have done after the order filled.

        Args:
            last_price (decimal.Decimal): The last traded price.

        Returns:
            bool: True when a buy's price was traded below, or a sell's above.
        """
        if self.side == 'BUY':
            return last_price < self.price
        return last_price > self.price

    def take_baseline(self, quote, volume):
        """Remembers a quote to compare the next one with, without reading anything into it.

        An order that has no place in the queue yet takes one here, behind whatever is visible at its price.

        Args:
            quote (dict): The unified quote.
            volume (int): Its day volume.

        Returns:
            None: This method returns nothing.
        """
        visible = self.visible_at_price(quote)
        if self.ahead is None and visible is not None:
            self.ahead = visible
        self.last_volume = volume
        self.last_broker = quote.get('broker')
        self.last_visible = visible
        self.needs_baseline = False

    def update(self, quote):
        """Moves the estimate on by one quote.

        A quote marked stale is ignored. A quote from a different broker than the last, or one whose volume went down, is not compared with the last: a change of broker can restart the volume count, and volume falling means a new session, whose queue has to be joined again from the back.

        Args:
            quote (dict): The unified quote.

        Returns:
            bool: True when the estimate changed.
        """
        if not isinstance(quote, dict) or quote.get('stale'):
            return False
        volume = self.as_quantity(quote.get('volume'))
        if volume is None:
            return False
        self.updated_at = quote.get('received_at')

        if self.touched_at is None and self.is_touched(quote):
            self.touched_at = quote.get('received_at')

        if self.last_volume is not None and volume < self.last_volume:
            self.ahead = None
            self.needs_baseline = True
        if quote.get('broker') != self.last_broker:
            self.needs_baseline = True
        if self.needs_baseline:
            self.take_baseline(quote, volume)
            self.updates = self.updates + 1
            return True

        traded = volume - self.last_volume
        last_price = self.as_price(quote.get('last_price'))
        visible = self.visible_at_price(quote)
        traded_at_price = 0
        if traded > 0 and last_price is not None:
            if self.traded_through(last_price):
                self.fill_through()
            elif last_price == self.price:
                traded_at_price = traded
                self.serve_queue(traded_at_price)
        self.count_cancellations(traded_at_price, visible)

        if self.ahead is None and visible is not None:
            self.ahead = visible
        self.last_volume = volume
        self.last_visible = visible
        self.updates = self.updates + 1
        return True

    def fill_through(self):
        """Fills the whole order, because the price traded beyond it.

        Returns:
            None: This method returns nothing.
        """
        self.ahead = 0
        self.queue_filled = self.quantity

    def serve_queue(self, traded_at_price):
        """Serves the queue at the order's price with what traded there, first whatever is ahead and then the order.

        An order whose place is unknown is not filled, since it cannot be told whether what traded reached it.

        Args:
            traded_at_price (int): The quantity that traded at the price.

        Returns:
            None: This method returns nothing.
        """
        if self.ahead is None:
            return
        taken_from_ahead = min(self.ahead, traded_at_price)
        self.ahead = self.ahead - taken_from_ahead
        left_over = traded_at_price - taken_from_ahead
        self.queue_filled = self.queue_filled + min(self.remaining(), left_over)

    def count_cancellations(self, traded_at_price, visible):
        """Shortens the queue ahead by its share of whatever left the level without trading.

        Args:
            traded_at_price (int): The quantity that traded at the price since the last quote.
            visible (int | None): The quantity visible at the price now.

        Returns:
            None: This method returns nothing.
        """
        if self.ahead is None or visible is None or self.last_visible is None:
            return
        level_after_trades = self.last_visible - traded_at_price
        cancelled = level_after_trades - visible
        if cancelled > 0 and level_after_trades > 0:
            share_ahead = (
                decimal.Decimal(self.ahead) /
                decimal.Decimal(level_after_trades)
            )
            cancelled_ahead = int(decimal.Decimal(cancelled) * share_ahead)
            self.ahead = self.ahead - cancelled_ahead
        if self.ahead > visible:
            self.ahead = visible
        if self.ahead < 0:
            self.ahead = 0
