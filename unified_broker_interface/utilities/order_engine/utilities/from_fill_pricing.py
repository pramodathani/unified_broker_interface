"""The pricing that places an exit a distance from the price its position was opened at."""

import decimal


class FromFillPricing:
    """A plan order's pricing for an exit set a distance from the opening fill, so one setting suits a position opened either way.

    It prices a Then join's child from the average fill of the orders that opened the position, which the plan reader lists in `opened_by`; under a two-sided breakout only the side that broke has filled, so the exit follows that side. With `stop_distance` the order is a native stop-limit: an exit that sells sits `stop_distance` below the fill and an exit that buys sits that far above it, with the limit `stop_limit_offset` further on, past the trigger. With `target_distance` the order is a limit on the profitable side: above the fill for a sell, below it for a buy. Prices are rounded to the nearest tick, and nothing is sent until the opening order has filled.

    Attributes:
        stop_distance (decimal.Decimal | None): How far from the fill a stop triggers, or None for a target.
        stop_limit_offset (decimal.Decimal | None): How far past its trigger a stop's limit sits, or None for a target.
        target_distance (decimal.Decimal | None): How far from the fill a target rests, or None for a stop.
        opened_by (list): The paths of the orders whose fills opened the position, which the plan reader sets.
    """

    def __init__(self, stop_distance, stop_limit_offset, target_distance):
        """Builds the pricing from distances the plan reader has already checked.

        Args:
            stop_distance (decimal.Decimal | None): The stop's distance from the fill, or None.
            stop_limit_offset (decimal.Decimal | None): The stop's limit past its trigger, or None.
            target_distance (decimal.Decimal | None): The target's distance from the fill, or None.

        Returns:
            None: This method returns nothing.
        """
        self.stop_distance = stop_distance
        self.stop_limit_offset = stop_limit_offset
        self.target_distance = target_distance
        self.opened_by = []

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def moves(self):
        """Whether this pricing moves a resting order, which it does not.

        Returns:
            bool: False.
        """
        return False

    def is_stop(self):
        """Whether this pricing sends a resting stop, which cannot be split into pieces.

        Returns:
            bool: True when it was given `stop_distance`.
        """
        return self.stop_distance is not None

    def opening_fill(self, parent, opening_side=None):
        """The average price the position was opened at.

        When both sides of a two-sided breakout filled, only the fills on the side the position is held count: a short opened at 990 and partly bought back at 1010 keeps its exits measured from 990, not from an average of the two.

        Args:
            parent (ParentOrder): The plan order's parent, holding the legs.
            opening_side (str | None): BUY or SELL, the side the position is held on, or None to count every fill.

        Returns:
            decimal.Decimal | None: The average fill price, or None before anything has filled.
        """
        filled = 0
        spent = decimal.Decimal(0)
        for leg in parent.legs:
            if leg.role not in self.opened_by or not leg.filled_quantity:
                continue
            if opening_side is not None and str(leg.transaction_type or '').upper() != opening_side:
                continue
            price = leg.average_price or leg.price
            if not price:
                continue
            filled = filled + leg.filled_quantity
            spent = spent + decimal.Decimal(str(price)) * leg.filled_quantity
        if filled == 0:
            return None
        return spent / filled

    def on_tick(self, price, tick_size):
        """A price rounded to the nearest tick.

        Args:
            price (decimal.Decimal): The price.
            tick_size (decimal.Decimal | None): The instrument's tick, or None to leave the price as it is.

        Returns:
            decimal.Decimal: The rounded price.
        """
        if not tick_size:
            return price
        ticks = (price / tick_size).to_integral_value(rounding=decimal.ROUND_HALF_UP)
        return (ticks * tick_size).quantize(tick_size)

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a stop-limit or a limit a distance from the opening fill, or None until the position has been opened at a usable price.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which knows the tick size.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side this exit is sent on.
            quotes (dict): Unused.
            memory (dict): Unused.

        Returns:
            dict | None: The body, or None when no price can be made.
        """
        del quotes, memory
        opening_side = 'SELL' if sending_side == 'BUY' else 'BUY'
        filled_at = self.opening_fill(plan_order.parent, opening_side)
        if filled_at is None:
            return None
        tick_size = plan_order.tick_size()
        if self.is_stop():
            away = decimal.Decimal(-1) if sending_side == 'SELL' else decimal.Decimal(1)
            trigger = self.on_tick(filled_at + away * self.stop_distance, tick_size)
            limit = self.on_tick(trigger + away * self.stop_limit_offset, tick_size)
            if trigger <= 0 or limit <= 0:
                return None
            body['order_type'] = 'SL'
            body['trigger_price'] = format(trigger, 'f')
            body['price'] = format(limit, 'f')
            return body
        towards_profit = decimal.Decimal(1) if sending_side == 'SELL' else decimal.Decimal(-1)
        price = self.on_tick(filled_at + towards_profit * self.target_distance, tick_size)
        if price <= 0:
            return None
        body['order_type'] = 'LIMIT'
        body['price'] = format(price, 'f')
        body.pop('trigger_price', None)
        return body

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The distances.
        """
        if self.is_stop():
            return {
                'from_fill': {
                    'stop_distance': str(self.stop_distance),
                    'stop_limit_offset': str(self.stop_limit_offset),
                },
            }
        return {
            'from_fill': {
                'target_distance': str(self.target_distance),
            },
        }
