"""The pricing that sends a limit a few ticks past the other side of the book, so it trades now."""


class MarketablePricing:
    """A plan order's pricing that sends a limit `buffer_ticks` past the opposite touch, read at the moment the order is sent.

    This is how market-if-touched, the hidden stop and every closing order price themselves today: a limit rather than a market order, so the fill can never be worse than the buffer allows, but far enough through the touch to fill against what is resting there. When the book has no opposite side, or a quote has not arrived yet, no price can be made, and the order waits for the next tick.

    Attributes:
        buffer_ticks (int): How many ticks past the touch the limit is priced.
    """

    def __init__(self, buffer_ticks):
        """Builds the pricing.

        Args:
            buffer_ticks (int): How many ticks past the touch the limit is priced.

        Returns:
            None: This method returns nothing.
        """
        self.buffer_ticks = buffer_ticks

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does.

        Returns:
            bool: True.
        """
        return True

    def moves(self):
        """Whether this pricing moves a resting order on later ticks, which it does not.

        Returns:
            bool: False.
        """
        return False

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a limit past the opposite touch, or None when the book gives nothing to price against.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the order is sent on.
            quotes (dict): The quotes, by instrument id.
            memory (dict): Unused, since this pricing remembers nothing.

        Returns:
            dict | None: The body, or None when no price can be made.
        """
        del memory
        view = plan_order.view(quotes)
        touch = view.opposite_touch(sending_side)
        if touch is None:
            return None
        price = view.moved(touch, self.buffer_ticks, sending_side, True)
        price = view.rounded(price, sending_side)
        if price is None or price <= 0:
            return None
        body['order_type'] = 'LIMIT'
        body['price'] = str(price)
        return body

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The buffer.
        """
        return {
            'marketable': {
                'buffer_ticks': self.buffer_ticks,
            },
        }
