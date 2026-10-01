"""The pricing that rests a limit at a named place in the book and moves it there on every tick."""

import decimal

REFERENCES = (
    'own_touch',
    'mid',
    'opposite_touch',
)


class PegPricing:
    """A plan order's pricing that keeps a limit at its reference in the book, moved `offset_ticks` away from filling.

    It keeps the rules of today's peg type. `own_touch` joins the best price on the order's own side, so a buy sits on the bid; `mid` sits between the touch; `opposite_touch` sits on the other side's touch and fills at once. A positive offset moves the order away from filling and a negative one towards it. The order is moved whenever its reference moves, through the engine's repricing throttle, which also refuses a move that changes nothing.

    With `follows` false the order is priced at its reference when it is sent and left there, as each of today's accumulation purchases is. With `within_body_price`, a body that is a limit with a price sets the worst price the order will take, and the order rests at that price when the book does not carry its reference.

    Attributes:
        reference (str): One of `REFERENCES`.
        offset_ticks (int): How many ticks away from the reference, positive away from filling.
        follows (bool): Whether the order is moved after its reference on later ticks.
        within_body_price (bool): Whether the body's limit price is the worst the order takes.
    """

    def __init__(self, reference, offset_ticks, follows=True, within_body_price=False):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            reference (str): One of `REFERENCES`.
            offset_ticks (int): How many ticks away from the reference.
            follows (bool): Whether the order is moved after its reference.
            within_body_price (bool): Whether the body's limit price is the worst it takes.

        Returns:
            None: This method returns nothing.
        """
        self.reference = reference
        self.offset_ticks = offset_ticks
        self.follows = follows
        self.within_body_price = within_body_price

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does.

        Returns:
            bool: True.
        """
        return True

    def moves(self):
        """Whether this pricing moves a resting order on later ticks, which it does unless told not to follow.

        Returns:
            bool: `follows`.
        """
        return self.follows

    def wanted_price(self, view, side):
        """Where the order should be, given the book as it is now.

        Args:
            view (MarketView): The order's quote.
            side (str): BUY or SELL, the side the order is sent on.

        Returns:
            decimal.Decimal | None: The price, or None when the book does not carry the reference yet.
        """
        if self.reference == 'mid':
            price = view.mid()
        elif self.reference == 'opposite_touch':
            price = view.opposite_touch(side)
        else:
            price = view.own_touch(side)
        if price is None:
            return None
        if self.offset_ticks:
            price = view.moved(price, self.offset_ticks, side, False)
        price = view.rounded(price, side)
        if price is None or price <= 0:
            return None
        return price

    def within(self, price, body, side):
        """The price held no worse than the body's limit, or the limit itself when the book gave no price.

        Args:
            price (decimal.Decimal | None): The price the reference gave, or None.
            body (dict): The order's body.
            side (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when there is neither a reference nor a limit.
        """
        if str(body.get('order_type') or '').upper() != 'LIMIT' or body.get('price') is None:
            return price
        limit = decimal.Decimal(str(body['price']))
        if price is None:
            return limit
        if side == 'BUY':
            return min(price, limit)
        return max(price, limit)

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a limit at the reference now, or None when the book does not carry it yet.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the order is sent on.
            quotes (dict): The quotes, by instrument id.
            memory (dict): Unused, since a peg remembers nothing.

        Returns:
            dict | None: The body, or None when no price can be made.
        """
        del memory
        price = self.wanted_price(plan_order.view(quotes), sending_side)
        if self.within_body_price:
            price = self.within(price, body, sending_side)
        if price is None:
            return None
        body['order_type'] = 'LIMIT'
        body['price'] = str(price)
        return body

    def moved_prices(self, plan_order, memory, leg, quotes, now):
        """Where the resting order should move to on this tick, or None when the book does not say.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            memory (dict): Unused, since a peg remembers nothing.
            leg (OrderLeg): The resting order.
            quotes (dict): The quotes the tick carried.
            now (float): Unused.

        Returns:
            tuple | None: The new limit (decimal.Decimal), no trigger (None) and a reason (str), or None.
        """
        del memory, now
        view = plan_order.view(quotes)
        if not view.is_readable():
            return None
        price = self.wanted_price(view, leg.transaction_type)
        if price is None:
            return None
        return price, None, f'the {self.reference} peg moved to {price}'

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'peg': {
                'reference': self.reference,
                'offset_ticks': self.offset_ticks,
                'follows': self.follows,
                'within_body_price': self.within_body_price,
            },
        }
