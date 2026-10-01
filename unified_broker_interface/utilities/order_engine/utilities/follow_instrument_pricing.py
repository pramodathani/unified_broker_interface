"""The pricing that moves a resting limit by how far another instrument has moved since it was placed."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class FollowInstrumentPricing:
    """A plan order's pricing that starts at the body's limit and moves it by `delta` times another instrument's move.

    It keeps the rules of today's underlying peg type: `price = start price + delta × (watched − watched at start)`, so a Nifty call bid with a delta of 0.5 rises by 20 when the index rises by 40, without reading the option's own thin book. `lowest` and `highest` bound the price, it never goes below one tick, and it moves only when it would move by at least `step_ticks`, because every move costs a place in the queue. The start price and the watched instrument's price when the order was sent are kept in the pricing's memory.

    Attributes:
        instrument_id (str): The instrument it follows.
        delta (decimal.Decimal): How much the price moves per unit the watched instrument moves.
        lowest (decimal.Decimal | None): The lowest price it will go to, or None.
        highest (decimal.Decimal | None): The highest price it will go to, or None.
        step_ticks (int): The smallest move worth sending, in ticks.
    """

    def __init__(self, instrument_id, delta, lowest, highest, step_ticks):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            instrument_id (str): The instrument it follows.
            delta (decimal.Decimal | None): How much the price moves per unit, or None for a subclass that works the price out another way.
            lowest (decimal.Decimal | None): The lowest price, or None.
            highest (decimal.Decimal | None): The highest price, or None.
            step_ticks (int): The smallest move worth sending.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.delta = delta
        self.lowest = lowest
        self.highest = highest
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

    def prepared_memory(self, plan_order):
        """Checks the order can follow the instrument when the plan is placed, and readies the memory.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: The pricing's first memory, which is empty.

        Raises:
            RefusedRequestError: With HTTP 400 when the order would follow its own instrument, or is not a limit with a price to start from.
        """
        if self.instrument_id == plan_order.instrument_id:
            raise RefusedRequestError.refusal(
                'follow_instrument follows another instrument; to follow the traded instrument itself use peg',
                400,
            )
        body = plan_order.body
        if str(body.get('order_type') or '').upper() != 'LIMIT' or body.get('price') is None:
            raise RefusedRequestError.refusal(
                'follow_instrument starts from the price you give, so the order must be a LIMIT with a price',
                400,
            )
        return {}

    def watched_price(self, plan_order, quotes):
        """The watched instrument's last traded price.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            quotes (dict): The quotes, by instrument id.

        Returns:
            decimal.Decimal | None: The price, or None when its quote does not carry one.
        """
        return plan_order.view(quotes, self.instrument_id).last()

    def bounded(self, plan_order, price, side, quotes):
        """The price held inside `lowest` and `highest`, at least one tick, and rounded onto the tick.

        Args:
            plan_order (PlanOrder): The plan order, which knows the tick size.
            price (decimal.Decimal): The price worked out.
            side (str): BUY or SELL, which way to round.
            quotes (dict): The quotes, for the order's own view.

        Returns:
            decimal.Decimal | None: The price, or None when it cannot be rounded.
        """
        if self.lowest is not None and price < self.lowest:
            price = self.lowest
        if self.highest is not None and price > self.highest:
            price = self.highest
        tick_size = plan_order.tick_size()
        if tick_size and price < tick_size:
            price = tick_size
        return plan_order.view(quotes).rounded(price, side)

    def target_price(self, plan_order, memory, side, watched, quotes, now):
        """Where the order should be for the watched instrument's price now.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The pricing's memory, holding `start_price` and `watched_start`.
            side (str): BUY or SELL.
            watched (decimal.Decimal): The watched instrument's price now.
            quotes (dict): The quotes the tick carried.
            now (float): Unused here.

        Returns:
            decimal.Decimal | None: The price, or None when it cannot be worked out.
        """
        del now
        start_price = decimal.Decimal(memory['start_price'])
        watched_start = decimal.Decimal(memory['watched_start'])
        price = start_price + self.delta * (watched - watched_start)
        return self.bounded(plan_order, price, side, quotes)

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body at its own limit, with the watched instrument's price now remembered as the start.

        Args:
            plan_order (PlanOrder): The plan order.
            body (dict): A copy of the order's body.
            sending_side (str): Unused, since the body's own price is sent.
            quotes (dict): The quotes, by instrument id.
            memory (dict): The pricing's memory, given `start_price` and `watched_start`.

        Returns:
            dict | None: The body, or None when the watched instrument has no price yet.
        """
        del sending_side
        watched = self.watched_price(plan_order, quotes)
        if watched is None:
            return None
        memory['start_price'] = str(body['price'])
        memory['watched_start'] = str(watched)
        body['order_type'] = 'LIMIT'
        return body

    def moved_prices(self, plan_order, memory, leg, quotes, now):
        """Where the resting order should move to on this tick, or None when the move would be too small.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The pricing's memory.
            leg (OrderLeg): The resting order.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            tuple | None: The new limit (decimal.Decimal), no trigger (None) and a reason (str), or None.
        """
        if leg.price is None or memory.get('watched_start') is None:
            return None
        watched = self.watched_price(plan_order, quotes)
        tick_size = plan_order.tick_size()
        if watched is None or not tick_size:
            return None
        price = self.target_price(plan_order, memory, leg.transaction_type, watched, quotes, now)
        if price is None:
            return None
        current = decimal.Decimal(str(leg.price))
        if abs(price - current) < tick_size * self.step_ticks:
            return None
        return price, None, self.reason(watched, price)

    def reason(self, watched, price):
        """Why the order moved, for the event log.

        Args:
            watched (decimal.Decimal): The watched instrument's price.
            price (decimal.Decimal): The new limit.

        Returns:
            str: The reason.
        """
        return f'the followed instrument is at {watched}, so the order moved to {price}'

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'follow_instrument': {
                'instrument_id': self.instrument_id,
                'delta': str(self.delta),
                'lowest': None if self.lowest is None else str(self.lowest),
                'highest': None if self.highest is None else str(self.highest),
                'step_ticks': self.step_ticks,
            },
        }
