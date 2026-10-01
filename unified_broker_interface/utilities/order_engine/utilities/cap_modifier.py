"""The pricing modifier that keeps an order's limit no worse than a stated price."""

import decimal


class CapModifier:
    """A plan order's price cap: the most a buy will pay and the least a sell will take.

    It keeps the cap of today's peg and chaser types and applies it to any pricing. Whatever the pricing works out, when the order is sent and every time it is moved, a limit past the cap is held at the cap rather than following, because the cap is what the caller said the trade is worth.

    Attributes:
        worst_price (decimal.Decimal): The cap.
    """

    def __init__(self, worst_price):
        """Builds the modifier from a price the plan reader has already checked.

        Args:
            worst_price (decimal.Decimal): The cap.

        Returns:
            None: This method returns nothing.
        """
        self.worst_price = worst_price

    def capped(self, price, side):
        """The price, held at the cap when it has gone past it.

        Args:
            price (decimal.Decimal): The price the pricing worked out.
            side (str): BUY or SELL, the side the order is sent on.

        Returns:
            decimal.Decimal: The price, or the cap.
        """
        if side == 'BUY':
            return min(price, self.worst_price)
        return max(price, self.worst_price)

    def capped_body(self, body, side):
        """The body with its limit price held at the cap, when it has one.

        Args:
            body (dict): The priced body, changed in place.
            side (str): BUY or SELL, the side the order is sent on.

        Returns:
            dict: The body.
        """
        if body.get('order_type') == 'MARKET' or body.get('price') is None:
            return body
        price = decimal.Decimal(str(body['price']))
        body['price'] = str(self.capped(price, side))
        return body

    def described(self):
        """This modifier as a dry run shows it.

        Returns:
            dict: The cap.
        """
        return {
            'cap': {
                'worst_price': str(self.worst_price),
            },
        }
