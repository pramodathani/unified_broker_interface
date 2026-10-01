"""The guard that sends a limit only when it would rest rather than trade."""

import decimal

ON_CROSSING = (
    'refuse',
    'rest',
)


class PostOnlyGuard:
    """A plan order's guard that checks a limit against the book before it is sent or moved, so it rests rather than takes.

    It keeps the rules of today's post-only type. Indian exchanges have no post-only flag, so this is an approximation: the book can move while the order is in flight. A buy is passive below the best offer and a sell above the best bid. A limit that would cross is either refused, which ends the order as refused, or, with `rest`, moved back to its own side's touch. A move of a resting order that would cross is skipped with `refuse` and held at the own touch with `rest`.

    Attributes:
        on_crossing (str): `refuse` or `rest`.
    """

    def __init__(self, on_crossing):
        """Builds the guard from a setting the plan reader has already checked.

        Args:
            on_crossing (str): `refuse` or `rest`.

        Returns:
            None: This method returns nothing.
        """
        self.on_crossing = on_crossing

    def would_cross(self, price, side, view):
        """Whether a limit at this price would trade against the other side.

        Args:
            price (decimal.Decimal): The limit.
            side (str): BUY or SELL.
            view (MarketView): The order's quote.

        Returns:
            bool: True when it would take liquidity.
        """
        touch = view.opposite_touch(side)
        if touch is None:
            return False
        if side == 'BUY':
            return price >= touch
        return price <= touch

    def checked_body(self, view, body, side):
        """The body once checked, a reason it is refused, or a sign that the book cannot be read yet.

        Args:
            view (MarketView): The order's quote.
            body (dict): The priced body, changed in place when it is moved back to rest.
            side (str): BUY or SELL, the side the order is sent on.

        Returns:
            tuple: The body (dict | None, None when the book cannot be read yet) and a refusal (str | None).
        """
        own = view.own_touch(side)
        if not view.is_readable() or own is None:
            return None, None
        if body.get('price') is None:
            return body, None
        price = decimal.Decimal(str(body['price']))
        if not self.would_cross(price, side, view):
            return body, None
        if self.on_crossing == 'refuse':
            return body, f'a post-only {side} at {price} would take liquidity against a book of {view.best_bid()} bid and {view.best_offer()} offered, so nothing was sent'
        body['price'] = str(own)
        return body, None

    def checked_move(self, view, price, side):
        """The price a resting order may move to, or None when the move must be skipped.

        Args:
            view (MarketView): The order's quote.
            price (decimal.Decimal): The price the pricing wants.
            side (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price to move to, or None.
        """
        if not self.would_cross(price, side, view):
            return price
        if self.on_crossing == 'refuse':
            return None
        return view.own_touch(side)

    def described(self):
        """This guard as a dry run shows it.

        Returns:
            dict: The setting.
        """
        return {
            'post_only': {
                'on_crossing': self.on_crossing,
            },
        }
