"""The pricing that starts a limit on its own side of the book and walks it towards the other until it trades."""

import decimal


class ChasePricing:
    """A plan order's pricing that joins its own side of the book and steps towards the other side until it fills.

    It keeps the rules of today's chaser type. The order starts at its own touch, and every `step_seconds` it moves `step_ticks` towards the market, from where it actually is rather than from where the book is, so it walks steadily and is never dragged backwards. It never steps past the other side's touch. With `cross_after_seconds`, once that long has passed since the first move was possible, the order is moved to the other side's touch, where it fills against what is resting. A cap on the price, if the order has one, holds every step.

    The clock starts on the first tick after the order rests, and both times are kept in the pricing's memory, which is recorded with each step so a restart neither steps at once nor forgets when the chase began.

    Attributes:
        step_ticks (int): How far each step moves, in ticks.
        step_seconds (float): How long it waits between steps.
        cross_after_seconds (float | None): How long it walks before crossing, or None to walk until it reaches the touch.
    """

    def __init__(self, step_ticks, step_seconds, cross_after_seconds):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            step_ticks (int): How far each step moves.
            step_seconds (float): How long it waits between steps.
            cross_after_seconds (float | None): How long before it crosses, or None.

        Returns:
            None: This method returns nothing.
        """
        self.step_ticks = step_ticks
        self.step_seconds = step_seconds
        self.cross_after_seconds = cross_after_seconds

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does.

        Returns:
            bool: True.
        """
        return True

    def moves(self):
        """Whether this pricing moves a resting order on later ticks, which it does.

        Returns:
            bool: True.
        """
        return True

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a limit at its own side's touch now, or None when the book does not carry that side yet.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the order is sent on.
            quotes (dict): The quotes, by instrument id.
            memory (dict): Unused; the clock starts on the first tick.

        Returns:
            dict | None: The body, or None when no price can be made.
        """
        del memory
        view = plan_order.view(quotes)
        if view.is_stale():
            return None
        price = view.own_touch(sending_side)
        if price is None:
            return None
        body['order_type'] = 'LIMIT'
        body['price'] = str(price)
        return body

    def no_further_than(self, price, limit, side):
        """The price, held back so it goes no further towards the market than `limit`.

        Args:
            price (decimal.Decimal): The price a step works out to.
            limit (decimal.Decimal): The furthest price allowed.
            side (str): BUY or SELL.

        Returns:
            decimal.Decimal: The price, or the limit.
        """
        if side == 'BUY':
            return min(price, limit)
        return max(price, limit)

    def carry_on(self, plan_order, memory, leg, before, quotes, now):
        """Restarts the wait before the next step, so the chase carries on from the price the caller set.

        The chase already steps from the order's own price, which now holds the caller's. Without a fresh wait the next tick could step straight away, moving the caller's price a moment after it was set. This keeps the rule of today's chaser.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): The pricing's memory, whose `stepped_at` is set in place.
            leg (OrderLeg): The chasing order, holding the caller's new price.
            before (dict): What the leg held before, with `price`.
            quotes (dict): Unused.
            now (float): The Unix time of the change.

        Returns:
            str | None: What changed, for the event log, or None when the price did not change.
        """
        del plan_order, quotes
        if leg.price == before.get('price'):
            return None
        if memory.get('started_at') is None:
            memory['started_at'] = now
        memory['stepped_at'] = now
        return f'the caller moved the price to {leg.price}, so the next step waits a full interval from now'

    def moved_prices(self, plan_order, memory, leg, quotes, now):
        """The step to take on this tick, the cross when the time is up, or None when it should wait.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            memory (dict): The pricing's memory, given `started_at` and `stepped_at` in place.
            leg (OrderLeg): The resting order.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            tuple | None: The new limit (decimal.Decimal), no trigger (None) and a reason (str), or None.
        """
        view = plan_order.view(quotes)
        if not view.is_readable() or view.is_stale() or leg.price is None:
            return None
        side = leg.transaction_type
        if memory.get('started_at') is None:
            memory['started_at'] = now
            memory['stepped_at'] = now
            return None
        if self.cross_after_seconds is not None and now - memory['started_at'] >= self.cross_after_seconds:
            touch = view.opposite_touch(side)
            if touch is None:
                return None
            return touch, None, f'the chase ran out of time and crossed to {touch}'
        if now - memory.get('stepped_at', 0) < self.step_seconds:
            return None
        here = view.rounded(decimal.Decimal(str(leg.price)), side)
        if here is None:
            return None
        price = view.moved(here, self.step_ticks, side, True)
        touch = view.opposite_touch(side)
        if touch is not None:
            price = self.no_further_than(price, touch, side)
        memory['stepped_at'] = now
        return price, None, f'the chase stepped to {price}'

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'chase': {
                'step_ticks': self.step_ticks,
                'step_seconds': self.step_seconds,
                'cross_after_seconds': self.cross_after_seconds,
            },
        }
