"""Buy once the price falls to a level, or sell once it rises to one."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)

DEFAULT_BUFFER_TICKS = 2


class MarketIfTouched(PriceTrigger):
    """An order that waits, hidden, for the price to touch a level and then takes what is there.

    This is the mirror image of a stop, and the reason it cannot be a native order in India. A native stop fires in the direction that runs away from you: a buy stop sits above the price, a sell stop below it. Most Indian brokers reject one placed on the other side. So "buy if the price *falls* to 990" has nowhere at the exchange to live.

    A resting limit order at 990 is the obvious alternative and is genuinely different. It is visible in the book, it fills at 990 or better and never worse, and it may sit through the level being touched without filling at all if the sellers are thin. A market-if-touched order is invisible until the moment it fires, and then it accepts the market price, which may be worse than 990 by the time it gets there. Which of the two you want depends on whether you would rather be certain of the price or certain of the trade.

    Since a market order in India is a protected limit order anyway, what fires here is a limit priced past the opposite touch by `buffer_ticks`, which is the Atlas's marketable limit. Two ticks is the default: enough to clear the touch on a normal book, narrow enough to stay inside the exchange's price bands.
    """

    SYNTHETIC_TYPE = 'market_if_touched'
    ARMED_MESSAGE = 'the price touches the level'

    def read_buffer_ticks(self):
        """How far past the touch the order it fires is priced.

        Returns:
            int: The buffer in ticks.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number of ticks at or above zero.
        """
        value = self.parent.parameters.get(
            'buffer_ticks',
            DEFAULT_BUFFER_TICKS,
        )
        try:
            ticks = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'buffer_ticks must be a whole number of ticks, not {value!r}',
                400,
            )
        if ticks < 0:
            raise RefusedRequestError.refusal(
                f'buffer_ticks cannot be negative, not {ticks}',
                400,
            )
        return ticks

    def child_order(self, order, view):
        """A limit priced past the opposite touch, which fills against what is resting there.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote at the moment it fired.

        Returns:
            PlaceOrderRequest | None: The order to place, or None when the book has no opposite side to price against.
        """
        touch = view.opposite_touch(order.transaction_type)
        if touch is None:
            return None
        price = view.moved(
            touch,
            self.read_buffer_ticks(),
            order.transaction_type,
            True,
        )
        price = view.rounded(price, order.transaction_type)
        if price is None or price <= 0:
            return None
        return self.priced(order, price)
