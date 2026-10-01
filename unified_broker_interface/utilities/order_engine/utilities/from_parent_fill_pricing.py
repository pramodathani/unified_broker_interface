"""The pricing that sets the second leg of a spread from what the first leg filled at."""

import decimal


class FromParentFillPricing:
    """A plan order's pricing for the second leg of a legged spread: whatever price makes the two legs add up to `net_price`, given the first leg's average fill.

    It keeps today's legged spread's arithmetic. `net_price` is the net debit per unit, positive when the spread costs money. The first leg's side signs its fill, a buy costing and a sell bringing money in, and the second leg's price is the net less that, signed by the second leg's own side. A price at or below zero cannot be sent, so the order waits. The first leg is the first plan of the Then join this order is the child of, whose path the plan reader sets.

    Attributes:
        net_price (decimal.Decimal): The net debit per unit aimed at.
        first_path (str | None): The path of the order whose fills price this one.
    """

    def __init__(self, net_price):
        """Builds the pricing from a price the plan reader has already checked.

        Args:
            net_price (decimal.Decimal): The net debit per unit.

        Returns:
            None: This method returns nothing.
        """
        self.net_price = net_price
        self.first_path = None

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

    def first_fill(self, parent):
        """The first leg's average fill price and side.

        Args:
            parent (ParentOrder): The plan order's parent, holding the legs.

        Returns:
            tuple | None: The average price (decimal.Decimal) and the side (str), or None before anything filled.
        """
        filled = 0
        spent = decimal.Decimal(0)
        side = None
        for leg in parent.legs:
            if leg.role != self.first_path or not leg.filled_quantity:
                continue
            price = leg.average_price or leg.price
            if not price:
                continue
            filled = filled + leg.filled_quantity
            spent = spent + decimal.Decimal(str(price)) * leg.filled_quantity
            side = leg.transaction_type
        if filled == 0:
            return None
        return spent / filled, side

    def second_price(self, filled_at, first_side, sending_side):
        """The second leg's price that makes the two add up to the net.

        Args:
            filled_at (decimal.Decimal): The first leg's average fill.
            first_side (str): BUY or SELL, the first leg's side.
            sending_side (str): BUY or SELL, this leg's side.

        Returns:
            decimal.Decimal: The price, which may be zero or below.
        """
        signed_fill = filled_at if first_side == 'BUY' else -filled_at
        wanted = self.net_price - signed_fill
        if sending_side == 'BUY':
            return wanted
        return -wanted

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a limit at the price that makes the spread's net, or None until the first leg has filled at a usable price.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, this leg's side.
            quotes (dict): Unused.
            memory (dict): Unused.

        Returns:
            dict | None: The body, or None when no price can be made.
        """
        del quotes, memory
        fill = self.first_fill(plan_order.parent)
        if fill is None:
            return None
        filled_at, first_side = fill
        price = self.second_price(filled_at, first_side, sending_side)
        if price <= 0:
            return None
        body['order_type'] = 'LIMIT'
        body['price'] = str(price)
        return body

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The net price.
        """
        return {
            'from_parent_fill': {
                'net_price': str(self.net_price),
            },
        }
