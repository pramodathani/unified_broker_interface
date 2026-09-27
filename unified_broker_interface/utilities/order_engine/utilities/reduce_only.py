"""The check that keeps a reduce-only order from opening or flipping a position."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)

POSITION_PRODUCTS = {
    'MIS': 'intraday',
    'CNC': 'delivery',
    'NRML': 'carry',
}


class ReduceOnlyCheck:
    """Whether one leg of a reduce-only order would only make the position it trades smaller.

    A reduce-only order (the Atlas's G11) is an exit that can never become an entry. A leg passes when it is on the side that closes the net position held in its instrument and product, and its quantity is no more than that position. Anything else, including any order when nothing is held, is refused before it is sent.

    Attributes:
        placement (EnginePlacement): What reads the positions.
    """

    def __init__(self, placement):
        """Builds the check.

        Args:
            placement (EnginePlacement): What reads the positions.

        Returns:
            None: This method returns nothing.
        """
        self.placement = placement

    def is_asked_for(self, parameters):
        """Whether the caller marked the order reduce-only.

        Args:
            parameters (dict): The parent's parameters.

        Returns:
            bool: True for a reduce-only order.

        Raises:
            RefusedRequestError: With HTTP 400 when `reduce_only` is not true or false.
        """
        value = parameters.get('reduce_only')
        if value is None or value is False:
            return False
        if value is True:
            return True
        raise RefusedRequestError.refusal(
            f'reduce_only must be true or false, not {value!r}',
            400,
        )

    def held(self, instrument_id, product):
        """The net quantity held in one instrument and product, positive meaning long.

        Args:
            instrument_id (str): The instrument.
            product (str): The order's product, on the request vocabulary such as `MIS`.

        Returns:
            decimal.Decimal: The net quantity, zero when nothing is held.
        """
        _, _, positions = self.placement.market_context(
            instrument_id,
            False,
            True,
        )
        wanted_product = POSITION_PRODUCTS.get(str(product or '').upper())
        total = decimal.Decimal(0)
        if not isinstance(positions, dict):
            return total
        for entry in positions.get('net') or []:
            if not isinstance(entry, dict):
                continue
            if entry.get('instrument_id') != instrument_id:
                continue
            entry_product = str(entry.get('product') or '').lower()
            if wanted_product is not None and entry_product != wanted_product:
                continue
            try:
                total = total + decimal.Decimal(str(entry.get('quantity', 0)))
            except (decimal.InvalidOperation, TypeError, ValueError):
                continue
        return total

    def refuse_if_it_adds(self, order, instrument_id):
        """Refuses a leg that would open, add to or flip the position it trades.

        Args:
            order (PlaceOrderRequest): The leg about to be sent.
            instrument_id (str): The instrument it trades.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 409 when the leg is not on the closing side of the position or is larger than it.
        """
        held = self.held(instrument_id, order.product)
        if held > 0:
            closing_side = 'SELL'
        elif held < 0:
            closing_side = 'BUY'
        else:
            closing_side = None
        if closing_side is None:
            raise RefusedRequestError.refusal(
                'the order is reduce-only and no position is held in this '
                f'instrument on {order.product}',
                409,
                instrument_id=instrument_id,
            )
        if order.transaction_type != closing_side:
            raise RefusedRequestError.refusal(
                f'the order is reduce-only, and a {order.transaction_type} '
                f'would add to the position of {held}',
                409,
                instrument_id=instrument_id,
            )
        if order.quantity > abs(held):
            raise RefusedRequestError.refusal(
                f'the order is reduce-only, and {order.quantity} is more than '
                f'the position of {abs(held)}, so it would open the other way',
                409,
                instrument_id=instrument_id,
            )
