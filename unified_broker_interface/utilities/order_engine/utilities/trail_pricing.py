"""The pricing that rests a stop-limit at the broker and moves it after the market."""

import decimal

HUNDRED = decimal.Decimal('100')


class TrailPricing:
    """A plan order's pricing that rests a native stop-limit and ratchets its trigger behind the best price seen.

    It keeps the rules of today's trailing stop and trailing entry. A sell stop sits below the market, remembers the highest last price seen, and follows it up at a fixed distance; a buy stop sits above the market and follows the lowest price down. The best price only ever moves in the favourable direction, so the stop does too, and a market that gives back part of its move leaves the stop where it was. The stop is moved only when it can move by at least `step_ticks`, which keeps modify traffic down, and every move passes the engine's repricing throttle and rate budget.

    The distance is `points`, or `percent` of the best price seen. `limit_offset` is how far past the trigger the limit sits, and it is required, because a stop-limit whose limit sits at its trigger does not fill when the price runs through it. The side the stop is on is the side the part sends: a part that protects a long sends a sell stop, and a trailing entry sends the caller's own side.

    Attributes:
        points (decimal.Decimal | None): The distance in price, or None when `percent` is used.
        percent (decimal.Decimal | None): The distance as a percentage of the best price, or None when `points` is used.
        limit_offset (decimal.Decimal): How far past the trigger the limit sits.
        step_ticks (int): The smallest move worth sending, in ticks.
    """

    def __init__(self, points, percent, limit_offset, step_ticks):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            points (decimal.Decimal | None): The distance in price, or None.
            percent (decimal.Decimal | None): The distance as a percentage, or None.
            limit_offset (decimal.Decimal): How far past the trigger the limit sits.
            step_ticks (int): The smallest move worth sending, in ticks.

        Returns:
            None: This method returns nothing.
        """
        self.points = points
        self.percent = percent
        self.limit_offset = limit_offset
        self.step_ticks = step_ticks

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

    def distance(self, best):
        """How far the trigger sits from the best price seen.

        Args:
            best (decimal.Decimal): The best price seen.

        Returns:
            decimal.Decimal: The distance, in price.
        """
        if self.points is not None:
            return self.points
        return best * self.percent / HUNDRED

    def improves(self, price, best, side):
        """Whether a price is better than the best seen for a stop on this side.

        Args:
            price (decimal.Decimal): The price just seen.
            best (decimal.Decimal | None): The best so far, or None before any.
            side (str): BUY or SELL, the side the stop trades.

        Returns:
            bool: True when the best price should move to this one.
        """
        if best is None:
            return True
        if side == 'SELL':
            return price > best
        return price < best

    def prices_from(self, view, best, side):
        """The stop's trigger and limit prices for a best price, rounded onto the tick.

        Args:
            view (MarketView): The quote, which rounds prices onto the tick.
            best (decimal.Decimal): The best price seen.
            side (str): BUY or SELL, the side the stop trades.

        Returns:
            tuple | None: The trigger and the limit (decimal.Decimal), or None when either cannot be rounded.
        """
        if side == 'SELL':
            trigger = best - self.distance(best)
        else:
            trigger = best + self.distance(best)
        trigger = view.rounded(trigger, side)
        if trigger is None:
            return None
        if side == 'SELL':
            limit = trigger - self.limit_offset
        else:
            limit = trigger + self.limit_offset
        limit = view.rounded(limit, side)
        if limit is None or limit <= 0 or trigger <= 0:
            return None
        return trigger, limit

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a stop-limit trailing the last traded price now, which becomes the first best price.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the stop trades.
            quotes (dict): The quotes, by instrument id.
            memory (dict): The pricing's memory, given `best`.

        Returns:
            dict | None: The body, or None when there is no last price to start from.
        """
        view = plan_order.view(quotes)
        start = view.last()
        if start is None:
            return None
        prices = self.prices_from(view, start, sending_side)
        if prices is None:
            return None
        trigger, limit = prices
        memory['best'] = str(start)
        body['order_type'] = 'SL'
        body['trigger_price'] = str(trigger)
        body['price'] = str(limit)
        return body

    def moved_prices(self, plan_order, memory, leg, quotes, now):
        """Where the resting stop should move to on this tick, or None when it should stay.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes and knows the tick size.
            memory (dict): The pricing's memory, whose `best` is updated in place.
            leg (OrderLeg): The resting stop.
            quotes (dict): The quotes the tick carried.
            now (float): Unused, since a trail follows prices rather than time.

        Returns:
            tuple | None: The new limit and trigger (decimal.Decimal) and a reason (str), or None.
        """
        del now
        view = plan_order.view(quotes)
        price = view.last()
        if price is None:
            return None
        side = leg.transaction_type
        best = None
        if memory.get('best') is not None:
            best = decimal.Decimal(str(memory['best']))
        if self.improves(price, best, side):
            best = price
            memory['best'] = str(best)
        prices = self.prices_from(view, best, side)
        if prices is None:
            return None
        trigger, limit = prices
        if leg.trigger_price is not None:
            current = decimal.Decimal(str(leg.trigger_price))
            step = plan_order.tick_size() * self.step_ticks
            if side == 'SELL' and trigger - current < step:
                return None
            if side == 'BUY' and current - trigger < step:
                return None
        return limit, trigger, f'the market reached {best}, so the stop follows to {trigger}'

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        settings = {
            'limit_offset': str(self.limit_offset),
            'step_ticks': self.step_ticks,
        }
        if self.points is not None:
            settings['points'] = str(self.points)
        else:
            settings['percent'] = str(self.percent)
        return {
            'trail': settings,
        }
