"""A stop that frees margin before it closes a position."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.position_closer import (
    PositionCloser,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    POSITION_PRODUCTS,
)


class CloseOnTrigger(PriceTrigger):
    """Waits for a price, then cancels every order resting on the instrument and closes the whole position (the Atlas's G12).

    A short option position ties up margin, and so does every pending order beside it. When the market runs against the position, the exit can be rejected for want of margin that the pending orders are holding, which is the worst moment for it. This type cancels them first, freeing the margin, and then sends the exit.

    It closes whatever is held on the instrument and the order's product when it fires, not a quantity named in advance, so a position that has grown or shrunk since the order was placed is still closed exactly. `transaction_type` is the side that opened the position, as for `trailing_stop`: a long is protected by a BUY, which fires when the price falls to the level. Nothing held when it fires completes the parent without sending anything.

    The cancels and the exit go through `PositionCloser`, the same steps `square_off` takes at a time of day.
    """

    SYNTHETIC_TYPE = 'close_on_trigger'
    ARMED_MESSAGE = 'the level is reached, and then every order on the instrument is cancelled and the position closed'

    def position_product(self, order):
        """The order's product, on the vocabulary the positions document uses.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.

        Returns:
            str: The product, such as `intraday`.

        Raises:
            RefusedRequestError: With HTTP 400 when the product has no position counterpart.
        """
        product = POSITION_PRODUCTS.get(str(order.product or '').upper())
        if product is None:
            raise RefusedRequestError.refusal(
                f'a close-on-trigger order closes a position on its product, '
                f'and {order.product!r} is not one',
                400,
            )
        return product

    def child_order(self, order, view):
        """The caller's own order, which here only says which side opened the position and on which product.

        The order actually sent is built by `fire` from the position held at that moment, after the cancels.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote.

        Returns:
            PlaceOrderRequest: The caller's order.
        """
        return order

    def fire(self, child, price, level):
        """Cancels every order resting on the instrument, then closes what is held.

        Args:
            child (PlaceOrderRequest): The caller's order.
            price (decimal.Decimal): The price that reached the level.
            level (decimal.Decimal): The level.

        Returns:
            bool: True, because the trigger fired whatever happened next.
        """
        closer = PositionCloser(self)
        instrument_ids = {
            self.parent.instrument_id,
        }
        cancelled = closer.cancel_resting(
            instrument_ids,
            'cancelled before closing the position, to free its margin',
        )
        positions = closer.open_positions(
            self.position_product(child),
            instrument_ids,
        )
        if not positions:
            self.record_state(
                'completed',
                f'{price} reached the trigger at {level}; {cancelled} '
                'resting orders cancelled and nothing was held to close',
            )
            self.save()
            return True
        outcome = None
        messages = []
        for broker_name, instrument_id, quantity in positions:
            closing = closer.closing_order(instrument_id, quantity)
            if closing is None:
                messages.append(
                    f'the book gave no price to close {abs(quantity)} at {broker_name}'
                )
                continue
            body, _, _ = self.place_leg(
                'close',
                closing,
                None,
                broker_name,
                instrument_id,
            )
            if outcome != 'accepted':
                outcome = body.get('outcome')
            messages.append(
                f'{body.get("status_message") or body.get("outcome")} closing '
                f'{abs(quantity)} at {broker_name}'
            )
        self.record_state(
            self.state_after_firing(outcome),
            f'{price} reached the trigger at {level}; {cancelled} resting '
            f'orders cancelled, then {"; ".join(messages)}',
        )
        self.save()
        return True

    def run(self, intent, started_at):
        """Records the order, refusing early when its product has no positions to close.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the product or the trigger cannot be read.
        """
        self.position_product(self.read_order(self.parent.body))
        return super().run(intent, started_at)
