"""An order fired by a comparison between two fields of a live quote."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)

WATCHABLE_FIELDS = (
    'last_price',
    'average_price',
    'previous_close',
    'best_bid',
    'best_offer',
    'mid',
)


class IndicatorTriggered(PriceTrigger):
    """A limit order sent when a named field of the quote crosses a level.

    Brokers sell this as conditional triggers or alert-linked orders, and the Atlas is right that underneath they are all the same thing as a limit-if-touched order with a different number being watched. The only question is which number.

    `watch_field` picks it. The interesting one is `average_price`, which is the volume weighted average price for the day: "buy when the price comes back below the day's average" is a complete strategy expressed in one order, and it cannot be written as a native stop because the average moves.

    **This is not an indicator library and is not trying to become one.** A relative strength index, a Supertrend or an open-interest change needs a history the engine does not keep and a recalculation schedule it does not run, and bolting a bar builder onto an order type would be building a second system inside this one. What is here is the part that belongs in an order: a value out of the live quote, a level, and a direction. Anything computed belongs in whatever decides to place the order, which then sends a plain limit or a limit-if-touched.

    `previous_close` is in the list because comparing against it is how "trigger if it goes green for the day" is written, and that one really is a property of the quote rather than of a strategy.
    """

    SYNTHETIC_TYPE = 'indicator_triggered'
    ARMED_MESSAGE = 'the watched field crosses the level'

    def read_field(self):
        """Which field of the quote this order watches.

        Returns:
            str: One of `WATCHABLE_FIELDS`.

        Raises:
            RefusedRequestError: With HTTP 400 when the caller named something else.
        """
        field = self.parent.parameters.get('watch_field', 'last_price')
        if field not in WATCHABLE_FIELDS:
            raise RefusedRequestError.refusal(
                f'watch_field must be one of {", ".join(WATCHABLE_FIELDS)}, '
                f'not {field!r}',
                400,
            )
        return field

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
                'an indicator-triggered order rests at a price of its own, so '
                'it needs limit_price as well as trigger_price',
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
        """Records the order, refusing early if the field or the limit price cannot be read.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the field, the trigger or the limit price cannot be read.
        """
        self.read_field()
        self.read_limit_price()
        return super().run(intent, started_at)

    def watched_price(self, view):
        """The field the caller named, out of the quote.

        Args:
            view (MarketView): The instrument's quote.

        Returns:
            decimal.Decimal | None: The value, or None when the quote does not carry it.
        """
        field = self.read_field()
        if field == 'best_bid':
            return view.best_bid()
        if field == 'best_offer':
            return view.best_offer()
        if field == 'mid':
            middle = view.mid()
            if middle is None:
                return None
            return view.rounded(middle)
        if not view.is_readable():
            return None
        return view.number(view.quote.get(field))

    def child_order(self, order, view):
        """A limit at the price the caller named.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote at the moment it fired.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        return self.priced(order, self.read_limit_price())
