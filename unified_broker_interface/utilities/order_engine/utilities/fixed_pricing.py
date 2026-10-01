"""The pricing that sends an order at the price the caller gave."""


class FixedPricing:
    """A plan order's pricing that sends the order at a price the caller gave, and never moves it.

    With no settings it is the body's own order type and price, which is what every order does today. `price` sends a limit at that price instead, as limit-if-touched does, and `order_type` names a `LIMIT` or a `MARKET` order.

    Attributes:
        price (decimal.Decimal | None): The limit price, or None for the body's.
        order_type (str | None): `LIMIT` or `MARKET`, or None for the body's.
    """

    def __init__(self, price, order_type):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            price (decimal.Decimal | None): The limit price, or None for the body's.
            order_type (str | None): `LIMIT` or `MARKET`, or None for the body's.

        Returns:
            None: This method returns nothing.
        """
        self.price = price
        self.order_type = order_type

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def moves(self):
        """Whether this pricing moves a resting order on later ticks, which it does not.

        Returns:
            bool: False.
        """
        return False

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body with this pricing's order type and price.

        Args:
            plan_order (PlanOrder): Unused.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): Unused.
            quotes (dict): Unused.
            memory (dict): Unused, since this pricing remembers nothing.

        Returns:
            dict: The body.
        """
        del plan_order, sending_side, quotes, memory
        if self.price is not None:
            body['order_type'] = 'LIMIT'
            body['price'] = str(self.price)
        if self.order_type is not None:
            body['order_type'] = self.order_type
        if body.get('order_type') == 'MARKET':
            body.pop('price', None)
        return body

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings, with the body's own values named where none were given.
        """
        settings = {
            'price': 'the body\'s price',
            'order_type': 'the body\'s order_type',
        }
        if self.price is not None:
            settings['price'] = str(self.price)
            settings['order_type'] = 'LIMIT'
        if self.order_type is not None:
            settings['order_type'] = self.order_type
        return {
            'fixed': settings,
        }
