"""The pricing that rests a stop-limit order at the broker."""


class NativeStopPricing:
    """A plan order's pricing that sends a stop-limit order, which the exchange holds until its trigger price trades.

    This is the stop in a bracket or a cover order. Unlike an engine-side trigger it goes on protecting the position while the engine is down, which is why exits default to it. The limit price is how far the stop may fill once triggered.

    Attributes:
        trigger_price (decimal.Decimal): The price at which the exchange triggers the stop.
        limit_price (decimal.Decimal): The worst price it may then fill at.
    """

    def __init__(self, trigger_price, limit_price):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            trigger_price (decimal.Decimal): The stop's trigger price.
            limit_price (decimal.Decimal): The stop's limit price.

        Returns:
            None: This method returns nothing.
        """
        self.trigger_price = trigger_price
        self.limit_price = limit_price

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def priced_body(self, plan_order, body, sending_side, quotes):
        """The body as a stop-limit order.

        Args:
            plan_order (PlanOrder): Unused.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): Unused.
            quotes (dict): Unused.

        Returns:
            dict: The body.
        """
        del plan_order, sending_side, quotes
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
            },
        }
