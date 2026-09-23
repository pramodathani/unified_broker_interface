"""Building the stop and target orders that protect a position, from what a caller asked for."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)

OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}


class ExitLegs:
    """Turns `{"stop_price": 990, "stop_limit_price": 988, "target_price": 1010}` into two orders.

    Shared by the bracket and the standalone OCO, because the two differ in what comes before the exits rather than in the exits themselves.

    **A stop needs both a trigger and a limit, and neither is defaulted.** The Atlas is emphatic that the way a stop fails in India is the gap: stop-loss-market is gone from NSE options and from BSE entirely, so a stop is a stop-limit, and a stop-limit whose limit sits at its trigger will simply not fill when the price runs through it. Defaulting the limit to the trigger would look convenient and would produce stops that do not work in exactly the conditions they exist for. Making the caller state both is the one place this class is deliberately unhelpful.

    NSE caps the gap between them — three per cent for cash-segment stocks above fifty rupees, one rupee fifty at or below — so a limit far from the trigger is refused by the exchange rather than by this.
    """

    def build(self, order, parameters, quantity):
        """The exit orders for a position of `quantity`, in the direction that closes it.

        Args:
            order (PlaceOrderRequest): The order whose side, product and instrument the exits take.
            parameters (dict): The caller's `synthetic` object.
            quantity (int): How much to protect, in units.

        Returns:
            list: One `(role, PlaceOrderRequest)` per exit, the stop first.

        Raises:
            RefusedRequestError: With HTTP 400 when neither exit is named, or a stop is named without both its prices.
        """
        stop_price = self.price(parameters, 'stop_price')
        stop_limit_price = self.price(parameters, 'stop_limit_price')
        target_price = self.price(parameters, 'target_price')
        if stop_price is None and target_price is None:
            raise RefusedRequestError.refusal(
                'this order type needs a stop_price, a target_price, or both',
                400,
            )
        if stop_price is not None and stop_limit_price is None:
            raise RefusedRequestError.refusal(
                'a stop needs stop_limit_price as well as stop_price: a '
                'stop-limit whose limit sits at its trigger will not fill when '
                'the price runs through it, which is what a stop is for',
                400,
            )

        exit_side = OPPOSITE_SIDES[order.transaction_type]
        legs = []
        if stop_price is not None:
            legs.append((
                'stop',
                self.exit_order(
                    order,
                    exit_side,
                    quantity,
                    'SL',
                    stop_limit_price,
                    stop_price,
                ),
            ))
        if target_price is not None:
            legs.append((
                'target',
                self.exit_order(
                    order,
                    exit_side,
                    quantity,
                    'LIMIT',
                    target_price,
                    None,
                ),
            ))
        return legs

    def exit_order(
        self,
        order,
        exit_side,
        quantity,
        order_type,
        price,
        trigger_price,
    ):
        """One exit order, copied from the parent's own order so it keeps its instrument and product.

        Args:
            order (PlaceOrderRequest): The order to copy.
            exit_side (str): `BUY` or `SELL`, the side that closes the position.
            quantity (int): The quantity in units.
            order_type (str): `SL` or `LIMIT`.
            price (decimal.Decimal): The limit price.
            trigger_price (decimal.Decimal | None): The trigger price, for a stop.

        Returns:
            PlaceOrderRequest: The exit order.
        """
        exit_order = order.with_quantities(quantity, 0)
        exit_order.transaction_type = exit_side
        exit_order.order_type = order_type
        exit_order.price = price
        exit_order.price_text = str(price)
        exit_order.price_number = float(price)
        exit_order.trigger_price = trigger_price
        exit_order.trigger_price_text = str(trigger_price or 0)
        exit_order.trigger_price_number = float(trigger_price or 0)
        # An exit the engine invented carries the parent's tag, not the caller's: the caller's tag
        # belongs to the order they asked for, and this is one they did not.
        exit_order.tag = None
        return exit_order

    def price(self, parameters, field_name):
        """One optional price from the caller's parameters.

        Args:
            parameters (dict): The caller's `synthetic` object.
            field_name (str): The field's name.

        Returns:
            decimal.Decimal | None: The price, or None when it was not given.

        Raises:
            RefusedRequestError: With HTTP 400 when the value is given but is not a price above zero.
        """
        value = parameters.get(field_name)
        if value is None:
            return None
        try:
            price = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError):
            price = None
        if price is None or not price.is_finite() or price <= 0:
            raise RefusedRequestError.refusal(
                f'{field_name} must be a price above zero',
                400,
            )
        return price
