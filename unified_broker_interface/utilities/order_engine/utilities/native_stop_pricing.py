"""The pricing that rests a stop-limit order at the broker."""

GAP_BUFFER_TICKS = 2


class NativeStopPricing:
    """A plan order's pricing that sends a stop-limit order, which the exchange holds until its trigger price trades.

    This is the stop in a bracket or a cover order. Unlike an engine-side trigger it goes on protecting the position while the engine is down, which is why exits default to it. The limit price is how far the stop may fill once triggered.

    With `exit_if_gapped`, a stop whose trigger the last price is already past when it is sent is sent instead as a limit two ticks past the other side's touch, as today's daily stop exits rather than arming a stop the open has gapped through: such a stop is refused by the broker or fires at whatever the gap left.

    Attributes:
        trigger_price (decimal.Decimal): The price at which the exchange triggers the stop.
        limit_price (decimal.Decimal): The worst price it may then fill at.
        exit_if_gapped (bool): Whether a stop the price has already passed is sent as a marketable limit.
    """

    def __init__(self, trigger_price, limit_price, exit_if_gapped=False):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            trigger_price (decimal.Decimal): The stop's trigger price.
            limit_price (decimal.Decimal): The stop's limit price.
            exit_if_gapped (bool): Whether a stop the price has already passed is sent as a marketable limit.

        Returns:
            None: This method returns nothing.
        """
        self.trigger_price = trigger_price
        self.limit_price = limit_price
        self.exit_if_gapped = exit_if_gapped

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does only to check for a gap.

        Returns:
            bool: `exit_if_gapped`.
        """
        return self.exit_if_gapped

    def moves(self):
        """Whether this pricing moves a resting order on later ticks, which it does not.

        Returns:
            bool: False.
        """
        return False

    def gapped_past(self, last, sending_side):
        """Whether the last price is already past the stop's trigger, so the stop would fire at once.

        Args:
            last (decimal.Decimal): The last traded price.
            sending_side (str): BUY or SELL, the side the stop trades.

        Returns:
            bool: True when it is.
        """
        if sending_side == 'SELL':
            return last <= self.trigger_price
        return last >= self.trigger_price

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a stop-limit order, or with `exit_if_gapped` a marketable limit when the price is already past the trigger.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which reads quotes into prices.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the stop trades.
            quotes (dict): The quotes, by instrument id.
            memory (dict): Unused, since this pricing remembers nothing.

        Returns:
            dict | None: The body, or None when a gap must be checked and the quote gives no last price yet.
        """
        del memory
        if self.exit_if_gapped:
            view = plan_order.view(quotes)
            last = view.last()
            if last is None:
                return None
            if self.gapped_past(last, sending_side):
                touch = view.opposite_touch(sending_side)
                if touch is None:
                    touch = last
                price = view.rounded(view.moved(touch, GAP_BUFFER_TICKS, sending_side, True), sending_side)
                if price is None or price <= 0:
                    return None
                body['order_type'] = 'LIMIT'
                body['price'] = str(price)
                body.pop('trigger_price', None)
                return body
        body['order_type'] = 'SL'
        body['trigger_price'] = str(self.trigger_price)
        body['price'] = str(self.limit_price)
        return body

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The trigger and limit prices.
        """
        return {
            'native_stop': {
                'trigger_price': str(self.trigger_price),
                'limit_price': str(self.limit_price),
                'exit_if_gapped': self.exit_if_gapped,
            },
        }
