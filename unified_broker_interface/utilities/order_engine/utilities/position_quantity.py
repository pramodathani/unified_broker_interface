"""An order's quantity read from the position held when it fires, and the closing of that position."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.position_closer import (
    PositionCloser,
)
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    POSITION_PRODUCTS,
)

PRODUCTS = (
    'intraday',
    'delivery',
    'carry',
)


class PositionQuantity:
    """A plan order sized by the position held when it fires, closed one order per broker that holds it, as today's close on trigger, square off and stop and reverse close.

    When the order fires it reads every broker's positions on its `product`, on its own instrument, on `instrument_ids`, or with `every_instrument` on every instrument. With `cancel_resting_first`, the default, every order resting on those instruments is cancelled first, because a stop or target left live would fill after the close and open a position the other way, and because cancelling frees the margin the close needs. Then each broker's share is closed at that broker with a limit two ticks past the other side's touch; `ratio` 2 sends twice each share, which closes the position and opens the reverse in one order.

    Attributes:
        product (str | None): `intraday`, `delivery` or `carry`, or None for the body's product.
        instrument_ids (list | None): The instruments to close, or None for the order's own.
        every_instrument (bool): Whether to close every instrument held on the product.
        ratio (int): 1 to close, 2 to close and reverse.
        cancel_resting_first (bool): Whether resting orders on those instruments are cancelled first.
    """

    def __init__(self, product, instrument_ids, every_instrument, ratio, cancel_resting_first):
        """Builds the quantity from settings the plan reader has already checked.

        Args:
            product (str | None): The product, or None for the body's.
            instrument_ids (list | None): The instruments, or None for the order's own.
            every_instrument (bool): Whether to close every instrument held.
            ratio (int): 1 or 2.
            cancel_resting_first (bool): Whether to cancel resting orders first.

        Returns:
            None: This method returns nothing.
        """
        self.product = product
        self.instrument_ids = instrument_ids
        self.every_instrument = every_instrument
        self.ratio = ratio
        self.cancel_resting_first = cancel_resting_first

    def product_of(self, context):
        """The product whose positions are closed.

        Args:
            context (OrderContext): The order's view of the plan order, whose body names a product.

        Returns:
            str | None: The product, or None when the body's product is not one positions are held on.
        """
        if self.product is not None:
            return self.product
        return POSITION_PRODUCTS.get(str(context.body.get('product') or '').upper())

    def wanted_instruments(self, context):
        """The instruments whose positions are closed.

        Args:
            context (OrderContext): The order's view of the plan order.

        Returns:
            set | None: The instrument ids, or None for every instrument.
        """
        if self.every_instrument:
            return None
        if self.instrument_ids:
            return set(self.instrument_ids)
        return {
            context.instrument_id,
        }

    def close(self, plan_order, context, path):
        """Cancels what rests, then closes what is held, one order per broker and instrument, at the broker that holds it.

        Args:
            plan_order (PlanOrder): The plan order, through which every cancel and order is recorded.
            context (OrderContext): The order's view of the plan order.
            path (str): The order's path, which every closing order carries as its role.

        Returns:
            tuple: The orders placed, as `(path, answer, status)`, and the positions found (int), and the resting orders cancelled (int).
        """
        closer = PositionCloser(plan_order)
        positions = closer.open_positions(self.product_of(context), self.wanted_instruments(context))
        cancelled = 0
        if self.cancel_resting_first:
            instrument_ids = self.wanted_instruments(context)
            if instrument_ids is None:
                instrument_ids = set()
                for _, instrument_id, _ in positions:
                    if instrument_id is not None:
                        instrument_ids.add(instrument_id)
            cancelled = closer.cancel_resting(instrument_ids, 'cancelled before closing the position, so it cannot re-open it, and to free its margin')
        placed = []
        for broker_name, instrument_id, quantity in positions:
            if instrument_id is None:
                continue
            closing = closer.closing_order(instrument_id, quantity * decimal.Decimal(self.ratio))
            if closing is None:
                continue
            body, status, _ = plan_order.place_leg(path, closing, None, broker_name, instrument_id)
            placed.append((path, body, status))
        return placed, len(positions), cancelled

    def described(self):
        """This quantity as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'position': {
                'product': self.product,
                'instrument_ids': self.instrument_ids,
                'every_instrument': self.every_instrument,
                'ratio': self.ratio,
                'cancel_resting_first': self.cancel_resting_first,
            },
        }
