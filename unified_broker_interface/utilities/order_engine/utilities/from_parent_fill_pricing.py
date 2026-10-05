"""The pricing that sets the second leg of a spread from what the first leg filled at."""

import decimal


class FromParentFillPricing:
    """A plan order's pricing for the second leg of a legged spread: whatever price makes the two legs add up to `net_price`, given the first leg's average fill.

    It keeps today's legged spread's arithmetic. `net_price` is the net debit per unit, positive when the spread costs money. The first leg's side signs its fill, a buy costing and a sell bringing money in, and the second leg's average is the net less the first leg's average, signed by the second leg's own side. Each new order of the second leg is priced so that it and the second leg's earlier orders together reach that average, since earlier orders priced from an earlier average would otherwise leave the net away from `net_price`. The price is rounded to the tick in the caller's favour, down for a buy and up for a sell, so the net is `net_price` or better. A price at or below zero cannot be sent, so the order waits. The first leg is the first plan of the Then join this order is the child of, and the plan reader sets both paths.

    Attributes:
        net_price (decimal.Decimal): The net debit per unit aimed at.
        first_path (str | None): The path of the order whose fills price this one.
        own_path (str | None): The path of the order this pricing prices, whose earlier orders count towards the net.
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
        self.own_path = None

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
        """The second leg's average price that makes the two add up to the net.

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

    def sent_before(self, parent):
        """How much the second leg's earlier orders account for, and at what cost.

        A finished order counts what it filled at its average price, and a resting one its whole quantity at its limit. A rejected order counts nothing.

        Args:
            parent (ParentOrder): The plan order's parent, holding the legs.

        Returns:
            tuple: The quantity (int) and its value at the prices counted (decimal.Decimal).
        """
        quantity = 0
        value = decimal.Decimal(0)
        for leg in parent.legs:
            if leg.role != self.own_path or leg.state == 'rejected':
                continue
            if leg.is_finished():
                counted = leg.filled_quantity or 0
                price = leg.average_price or leg.price
            else:
                counted = leg.quantity or 0
                price = leg.price
            if not counted or not price:
                continue
            quantity = quantity + counted
            value = value + decimal.Decimal(str(price)) * counted
        return quantity, value

    def next_price(self, parent, average, quantity):
        """The price of a new order of `quantity` that brings the second leg's average to `average`.

        Args:
            parent (ParentOrder): The plan order's parent, holding the legs.
            average (decimal.Decimal): The second leg's average price wanted.
            quantity (int): The new order's quantity.

        Returns:
            decimal.Decimal: The price, before rounding to the tick.
        """
        before_quantity, before_value = self.sent_before(parent)
        if quantity <= 0:
            return average
        return (average * (before_quantity + quantity) - before_value) / quantity

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a limit at the price that makes the spread's net, or None until the first leg has filled at a usable price.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which gives its tick size.
            body (dict): A copy of the order's body, holding the new order's quantity, changed in place.
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
        average = self.second_price(filled_at, first_side, sending_side)
        try:
            quantity = int(body.get('quantity') or 0)
        except (TypeError, ValueError):
            quantity = 0
        price = self.next_price(plan_order.parent, average, quantity)
        tick_size = plan_order.tick_size()
        if tick_size:
            rounding = decimal.ROUND_FLOOR if sending_side == 'BUY' else decimal.ROUND_CEILING
            price = (price / tick_size).to_integral_value(rounding=rounding) * tick_size
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
