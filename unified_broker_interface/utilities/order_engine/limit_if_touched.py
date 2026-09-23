"""Rest a limit at one price once the market touches another."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)


class LimitIfTouched(PriceTrigger):
    """An order that waits for the price to touch a level and then rests a limit at a different one.

    The point is that the two prices are allowed to differ. A market-if-touched order fires and takes whatever the book offers; this one fires and asks. When Nifty tags 25,000, bid for the option at what you think it is worth, not at what somebody is asking for it.

    That makes it the shape almost every conditional order in a broker's user interface really has underneath. An alert that places an order, a trigger sheet, a "buy when it breaks out" button: all of them watch one number and send a limit at another.

    `limit_price` is the price the order rests at. It is required, and deliberately not defaulted to the trigger level, because the two being the same is a choice rather than an obvious fallback, and an order that quietly rests at its own trigger is the kind of thing that looks right in a log and is wrong in the account.
    """

    SYNTHETIC_TYPE = 'limit_if_touched'
    ARMED_MESSAGE = 'the price touches the level'

    def read_limit_price(self):
        """The price the order rests at once it fires.

        Returns:
            decimal.Decimal: The limit price.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a price above zero.
        """
        value = self.parent.parameters.get('limit_price')
        if value is None:
            raise RefusedRequestError.refusal(
                'a limit-if-touched order rests at a price of its own, so it '
                'needs limit_price as well as trigger_price',
                400,
            )
        try:
            price = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'limit_price must be a price, not {value!r}',
                400,
            )
        if price <= 0:
            raise RefusedRequestError.refusal(
                f'limit_price must be above zero, not {price}',
                400,
            )
        return price

    def run(self, intent, started_at):
        """Records the order, refusing early if its limit price cannot be read.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the trigger or the limit price cannot be read.
        """
        self.read_limit_price()
        return super().run(intent, started_at)

    def child_order(self, order, view):
        """A limit at the price the caller named.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote at the moment it fired.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        return self.priced(order, self.read_limit_price())
