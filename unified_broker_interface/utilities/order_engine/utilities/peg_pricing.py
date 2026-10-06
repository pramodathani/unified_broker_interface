"""The pricing that rests a limit at a named place in the book and moves it there on every tick."""

import decimal

from unified_broker_interface.utilities.execution_costs.pre_trade_estimate import (
    PreTradeEstimate,
)

REFERENCES = (
    'own_touch',
    'mid',
    'opposite_touch',
)
ON_EMPTY_BOOK = (
    'wait',
    'refuse',
)


class PegPricing:
    """A plan order's pricing that keeps a limit at its reference in the book, moved `offset_ticks` away from filling.

    It keeps the rules of today's peg type. `own_touch` joins the best price on the order's own side, so a buy sits on the bid; `mid` sits between the touch; `opposite_touch` sits on the other side's touch and fills at once. A positive offset moves the order away from filling and a negative one towards it. The order is moved whenever its reference moves, through the engine's repricing throttle, which also refuses a move that changes nothing.

    With `follows` false the order is priced at its reference when it is sent and left there, as each of today's accumulation purchases is. With `within_body_price`, a body that is a limit with a price sets the worst price the order will take, and the order rests at that price when the book does not carry its reference.

    With `on_empty_book` set to `refuse`, an order that cannot be priced when it is first sent is refused rather than left waiting for a tick that carries its reference. This is what lets a market order sent as a marketable limit fail when nobody is on the other side, as a market order would, instead of waiting for someone to arrive.

    With `maximum_cost_bps` set, an order is refused before it is sent when crossing the spread for its whole quantity, as `PreTradeEstimate` works it out from the visible book, would cost more than that many basis points of the mid-price, or when the visible book does not hold its whole quantity, so the cost cannot be known. Both sides of the book must be visible to estimate; with one side empty the guard says nothing and the order is priced as before.

    Attributes:
        reference (str): One of `REFERENCES`.
        offset_ticks (int): How many ticks away from the reference, positive away from filling.
        follows (bool): Whether the order is moved after its reference on later ticks.
        within_body_price (bool): Whether the body's limit price is the worst the order takes.
        on_empty_book (str): One of `ON_EMPTY_BOOK`, what happens when the order cannot be priced when it is first sent.
        maximum_cost_bps (decimal.Decimal | None): The most the order may be estimated to cost to cross the spread, in basis points, or None for no limit.
    """

    def __init__(self, reference, offset_ticks, follows=True, within_body_price=False, on_empty_book='wait', maximum_cost_bps=None):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            reference (str): One of `REFERENCES`.
            offset_ticks (int): How many ticks away from the reference.
            follows (bool): Whether the order is moved after its reference.
            within_body_price (bool): Whether the body's limit price is the worst it takes.
            on_empty_book (str): `wait` to wait for a tick that carries the reference, or `refuse` to refuse the order.
            maximum_cost_bps (decimal.Decimal | int | float | None): The most the order may be estimated to cost, in basis points, or None for no limit.

        Returns:
            None: This method returns nothing.
        """
        self.reference = reference
        self.offset_ticks = offset_ticks
        self.follows = follows
        self.within_body_price = within_body_price
        self.on_empty_book = on_empty_book
        self.maximum_cost_bps = None
        if maximum_cost_bps is not None:
            self.maximum_cost_bps = decimal.Decimal(str(maximum_cost_bps))

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

    def reference_price(self, view, side):
        """The reference in the book as it is now, before any offset.

        Args:
            view (MarketView): The order's quote.
            side (str): BUY or SELL, the side the order is sent on.

        Returns:
            decimal.Decimal | None: The price, or None when the book does not carry the reference yet.
        """
        if self.reference == 'mid':
            return view.mid()
        if self.reference == 'opposite_touch':
            return view.opposite_touch(side)
        return view.own_touch(side)

    def offset(self, memory):
        """How many ticks from the reference the order rests: the offset a caller's change set, or the plan's own.

        Args:
            memory (dict): The pricing's memory, which holds `offset_ticks` once a caller has moved the order.

        Returns:
            int: The offset, positive away from filling.
        """
        if memory.get('offset_ticks') is not None:
            return int(memory['offset_ticks'])
        return self.offset_ticks

    def wanted_price(self, view, side, offset_ticks=None):
        """Where the order should be, given the book as it is now.

        Args:
            view (MarketView): The order's quote.
            side (str): BUY or SELL, the side the order is sent on.
            offset_ticks (int | None): The offset to use, or None for the plan's own.

        Returns:
            decimal.Decimal | None: The price, or None when the book does not carry the reference yet.
        """
        if offset_ticks is None:
            offset_ticks = self.offset_ticks
        price = self.reference_price(view, side)
        if price is None:
            return None
        if offset_ticks:
            price = view.moved(price, offset_ticks, side, False)
        price = view.rounded(price, side)
        if price is None or price <= 0:
            return None
        return price

    def empty_book_refusal(self, view, side):
        """Why an order that could not be priced is refused, or None when it waits for a tick that can price it.

        It is asked only once `priced_body` has given no price, so it names whichever reason the book gives: no quote yet, a quote marked stale, or no one on the side the reference reads.

        Args:
            view (MarketView): The order's quote.
            side (str): BUY or SELL, the side the order is sent on.

        Returns:
            str | None: The refusal, or None when `on_empty_book` is `wait`.
        """
        if self.on_empty_book != 'refuse':
            return None
        if not view.is_readable():
            return f'no live quote has arrived for this instrument, so the {side} could not be priced and nothing was sent'
        if view.is_stale():
            return f'the live quote for this instrument is marked stale, so the {side} could not be priced and nothing was sent'
        if self.reference == 'opposite_touch' and side == 'BUY':
            return 'nobody is offering this instrument, so the BUY could not be priced and nothing was sent'
        if self.reference == 'opposite_touch':
            return 'nobody is bidding for this instrument, so the SELL could not be priced and nothing was sent'
        return f'the book gives no {self.reference} price for this instrument, so the {side} could not be priced and nothing was sent'

    def cost_refusal(self, view, side, quantity):
        """Why an order is refused for costing too much to cross the spread, or None when it may be sent.

        Args:
            view (MarketView): The order's quote.
            side (str): BUY or SELL, the side the order is sent on.
            quantity (object): The order's quantity in units, from its body.

        Returns:
            str | None: The refusal, or None when there is no maximum, the quantity is not a positive whole number, the book cannot be priced, or the estimate is within the maximum.
        """
        if self.maximum_cost_bps is None:
            return None
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            return None
        estimate = PreTradeEstimate(
            side,
            quantity,
            view.levels_with_quantity('buy'),
            view.levels_with_quantity('sell'),
        )
        if not estimate.is_priceable():
            return None
        if not estimate.is_covered_by_book():
            visible = estimate.walk.visible_quantity()
            return f'the visible book holds only {visible} of the {quantity} units this {side} needs, so what crossing the spread would cost cannot be estimated and nothing was sent; a type that sends it in pieces, such as twap, participation or iceberg, can work it instead'
        cost = estimate.basis_points()
        if cost > self.maximum_cost_bps:
            return f'crossing the spread now would cost an estimated {cost} basis points, more than the maximum of {self.maximum_cost_bps}, so nothing was sent'
        return None

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
        view = plan_order.view(quotes)
        if view.is_stale():
            return None
        price = self.wanted_price(view, sending_side)
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
            memory (dict): The pricing's memory, which holds `offset_ticks` once a caller has moved the order.
            leg (OrderLeg): The resting order.
            quotes (dict): The quotes the tick carried.
            now (float): Unused.

        Returns:
            tuple | None: The new limit (decimal.Decimal), no trigger (None) and a reason (str), or None.
        """
        del now
        view = plan_order.view(quotes)
        if not view.is_readable() or view.is_stale():
            return None
        price = self.wanted_price(view, leg.transaction_type, self.offset(memory))
        if price is None:
            return None
        return price, None, f'the {self.reference} peg moved to {price}'

    def carry_on(self, plan_order, memory, leg, before, quotes, now):
        """Takes the offset from the reference that puts the peg at the price the caller set, so it follows the market from there.

        Without a new offset the next tick would move the order straight back to where the old offset puts it. The reference is read from the quote now, and the offset is the whole number of ticks between it and the caller's price. When the quote does not carry the reference, the offset is left as it was and the next tick moves the order back. This keeps the rule of today's peg.

        Args:
            plan_order (OrderContext): The plan order's context for this order, which knows the tick size.
            memory (dict): The pricing's memory, whose `offset_ticks` is set in place.
            leg (OrderLeg): The pegged order, holding the caller's new price.
            before (dict): What the leg held before, with `price`.
            quotes (dict): The quotes now, by instrument id.
            now (float): Unused.

        Returns:
            str | None: What changed, for the event log, or None when nothing did.
        """
        del now
        if leg.price is None or leg.price == before.get('price'):
            return None
        reference_price = self.reference_price(plan_order.view(quotes), leg.transaction_type)
        tick_size = plan_order.tick_size()
        if reference_price is None or not tick_size:
            return None
        new_price = decimal.Decimal(str(leg.price))
        if leg.transaction_type == 'BUY':
            distance = reference_price - new_price
        else:
            distance = new_price - reference_price
        offset = int((distance / tick_size).to_integral_value(rounding=decimal.ROUND_FLOOR))
        memory['offset_ticks'] = offset
        return f'the caller moved the price to {new_price}, so the peg rests {offset} ticks from its {self.reference}'

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings, with `maximum_cost_bps` only when one is set.
        """
        settings = {
            'reference': self.reference,
            'offset_ticks': self.offset_ticks,
            'follows': self.follows,
            'within_body_price': self.within_body_price,
            'on_empty_book': self.on_empty_book,
        }
        if self.maximum_cost_bps is not None:
            settings['maximum_cost_bps'] = float(self.maximum_cost_bps)
        return {
            'peg': settings,
        }
