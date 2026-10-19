"""What happened to one protective stop after its trigger fired: where the position it protected was actually closed."""

import decimal

BASIS_POINTS = decimal.Decimal(10000)
PRICE_PLACES = decimal.Decimal('0.0001')
BASIS_POINT_PLACES = decimal.Decimal('0.01')

ROW_COLUMNS = [
    'fired_at',
    'parent_order_id',
    'instrument_id',
    'segment',
    'transaction_type',
    'trigger_field',
    'trigger_price',
    'closed_by',
    'filled_quantity',
    'average_price',
    'slip',
    'slip_basis_points',
]


class StopOutcome:
    """One fired protective stop and the fill that closed its position.

    A stop held in the engine fires when its price field crosses the trigger, and then sends its own order. That order usually fills, a little beyond the trigger. When it does not fill in time, the strategy often cancels it and closes the position with an order of its own, which fills further away still. Both are the price the stop really got, so the close is recorded either way: `closed_by` is `stop` when the stop's own order filled, `other_order` when another order on the same instrument and side filled soon after the stop fired, and None when no fill was found.

    The slip is how far the fill was beyond the trigger, positive when it was worse: below the trigger for a sell, above it for a buy.

    Attributes:
        parent_order_id (str): The stop's parent order id.
        instrument_id (str): The instrument it protected.
        segment (str | None): The instrument's catalogue segment, or None when it is not known.
        transaction_type (str): `SELL` for a stop protecting a bought position, `BUY` for one protecting a sold position.
        trigger_field (str): The price the trigger watched, such as `bid`.
        trigger_price (decimal.Decimal): The trigger level.
        fired_at (datetime.datetime): When the trigger fired.
        closed_by (str | None): `stop`, `other_order`, or None while no fill is known.
        filled_quantity (int | None): The units the closing fill was for.
        average_price (decimal.Decimal | None): The closing fill's average price.
    """

    def __init__(
        self,
        parent_order_id,
        instrument_id,
        segment,
        transaction_type,
        trigger_field,
        trigger_price,
        fired_at,
    ):
        """Builds the outcome of a fired stop whose close is not yet known.

        Args:
            parent_order_id (str): The stop's parent order id.
            instrument_id (str): The instrument.
            segment (str | None): The catalogue segment, or None.
            transaction_type (str): `SELL` or `BUY`, the side of the stop's order.
            trigger_field (str): The price the trigger watched.
            trigger_price (decimal.Decimal): The trigger level.
            fired_at (datetime.datetime): When the trigger fired.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = parent_order_id
        self.instrument_id = instrument_id
        self.segment = segment
        self.transaction_type = transaction_type
        self.trigger_field = trigger_field
        self.trigger_price = decimal.Decimal(trigger_price)
        self.fired_at = fired_at
        self.closed_by = None
        self.filled_quantity = None
        self.average_price = None

    def record_close(self, closed_by, filled_quantity, average_price):
        """Records the fill that closed the position.

        Args:
            closed_by (str): `stop` or `other_order`.
            filled_quantity (int): The units filled.
            average_price (decimal.Decimal): The fill's average price.

        Returns:
            None: This method returns nothing.
        """
        self.closed_by = closed_by
        self.filled_quantity = filled_quantity
        self.average_price = decimal.Decimal(average_price)

    def is_resolved(self):
        """Whether a closing fill is known.

        Returns:
            bool: True once a close has been recorded.
        """
        return self.average_price is not None

    def slip(self):
        """How far the close was beyond the trigger, per unit.

        Returns:
            decimal.Decimal | None: Positive when the fill was worse than the trigger, or None when no close is known.
        """
        if self.average_price is None:
            return None
        if self.transaction_type == 'SELL':
            difference = self.trigger_price - self.average_price
        else:
            difference = self.average_price - self.trigger_price
        return difference.quantize(PRICE_PLACES)

    def slip_fraction(self):
        """The slip as a share of the trigger price, unrounded.

        Returns:
            decimal.Decimal | None: The share, or None when no close is known or the trigger is zero.
        """
        slip = self.slip()
        if slip is None or self.trigger_price == 0:
            return None
        return slip / self.trigger_price

    def slip_basis_points(self):
        """The slip in basis points of the trigger price.

        Returns:
            decimal.Decimal | None: The basis points to two places, or None when no close is known.
        """
        fraction = self.slip_fraction()
        if fraction is None:
            return None
        return (fraction * BASIS_POINTS).quantize(BASIS_POINT_PLACES)

    def row(self):
        """The outcome as a row of `unified.stop_slippage`.

        Returns:
            dict: One value per name in `ROW_COLUMNS`.
        """
        return {
            'fired_at': self.fired_at,
            'parent_order_id': self.parent_order_id,
            'instrument_id': self.instrument_id,
            'segment': self.segment,
            'transaction_type': self.transaction_type,
            'trigger_field': self.trigger_field,
            'trigger_price': self.trigger_price,
            'closed_by': self.closed_by,
            'filled_quantity': self.filled_quantity,
            'average_price': self.average_price,
            'slip': self.slip(),
            'slip_basis_points': self.slip_basis_points(),
        }
