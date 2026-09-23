"""Working a quantity out from the position held, so a caller can ask to close rather than count."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class QuantityReference:
    """Turns `{"kind": "reduce_position", "product": "mis"}` into a quantity and a side.

    This is the quantity half of what makes `TradeableInstrument`'s thirty-three order-placing methods a cross product rather than thirty-three types. `liquidate_position` also decides the side, because closing a long is selling and closing a short is buying, and making the caller work that out is exactly the sort of arithmetic that goes wrong under pressure.

    It reads no store: the engine reads `unified:portfolio:positions` and hands the document in.

    Quantities here are in units, as `POST /api/orders/place` takes them, not in a broker's lots. The conversion into a broker's own terms happens later and unchanged, so a reduce that is not a whole number of lots is refused by the same check that refuses a caller's own number.
    """

    def resolve(self, reference, positions, instrument_id, transaction_type, requested):
        """The quantity and side a reference names.

        Args:
            reference (dict): The parsed `quantity_reference`.
            positions (dict | None): The document `unified:portfolio:positions` holds.
            instrument_id (str): The instrument the order is for.
            transaction_type (str): The side the caller asked for.
            requested (int): The quantity the caller asked for, which may be zero.

        Returns:
            tuple: The quantity (int) and the transaction type (str) to send.

        Raises:
            RefusedRequestError: With HTTP 503 when the positions cannot be read, and 409 when there is no position to reduce or liquidate.
        """
        kind = reference['kind']
        if kind in ('absolute', 'add_to_position'):
            if requested < 1:
                raise RefusedRequestError.refusal(
                    f'a {kind} quantity_reference needs a quantity of at '
                    'least 1',
                    400,
                )
            return requested, transaction_type

        held = self.position_quantity(
            positions,
            instrument_id,
            reference.get('product'),
            kind,
        )
        if held == 0:
            raise RefusedRequestError.refusal(
                f'a {kind} quantity_reference found no open position in this '
                'instrument, so there is nothing to close',
                409,
                instrument_id=instrument_id,
            )
        closing_side = 'SELL' if held > 0 else 'BUY'
        if kind == 'liquidate_position':
            return abs(held), closing_side
        # reduce_position: the caller's quantity is a ceiling, not an instruction, so closing more
        # than is held is not possible however large a number was asked for.
        if requested < 1:
            return abs(held), closing_side
        return min(requested, abs(held)), closing_side

    def position_quantity(self, positions, instrument_id, product, kind):
        """The net quantity held in one instrument, signed, positive meaning long.

        Rows are matched on the instrument and, when the reference names one, the product. Without a product every product is added together, which is what somebody asking to liquidate an instrument means.

        Args:
            positions (dict | None): The document `unified:portfolio:positions` holds.
            instrument_id (str): The instrument.
            product (str | None): The product, on the vocabulary the REST API answers with.
            kind (str): The reference's kind, for the message.

        Returns:
            int: The net quantity.

        Raises:
            RefusedRequestError: With HTTP 503 when the positions document cannot be read.
        """
        if not isinstance(positions, dict):
            raise RefusedRequestError.refusal(
                f'a {kind} quantity_reference needs the unified positions and '
                'they could not be read',
                503,
            )
        rows = positions.get('net')
        if not isinstance(rows, list):
            raise RefusedRequestError.refusal(
                f'a {kind} quantity_reference needs the unified positions and '
                'they carry no net rows',
                503,
            )
        total = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get('instrument_id')) != str(instrument_id):
                continue
            if product and str(row.get('product') or '').lower() != product:
                continue
            total = total + self.whole(row.get('quantity'))
        return total

    def whole(self, value):
        """A signed quantity as an integer, or zero when it cannot be read.

        Args:
            value (object): The value.

        Returns:
            int: The quantity.
        """
        if value is None:
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
