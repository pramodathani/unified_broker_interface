"""An order's size as a ratio of what the first plan of a Then join filled, in whole lots."""

import decimal


class FillRatio:
    """A plan order sized at `ratio` times the quantity a Then join hands it, which is what the first plan has filled, rounded to whole lots when asked.

    It keeps today's attached hedge's sizing: a stock of 1,000 hedged at a ratio of 0.5 in a future whose lot is 250 wants two lots, and nothing is sent until a whole lot is missing. The lot is the order's own instrument's lot at the broker the plan's orders go to.

    Attributes:
        ratio (decimal.Decimal): The multiple of what filled, above zero.
        whole_lots (bool): Whether the size is rounded to the nearest whole lot.
    """

    def __init__(self, ratio, whole_lots):
        """Builds the sizing from settings the plan reader has already checked.

        Args:
            ratio (decimal.Decimal): The multiple of what filled.
            whole_lots (bool): Whether to round to whole lots.

        Returns:
            None: This method returns nothing.
        """
        self.ratio = ratio
        self.whole_lots = whole_lots

    def lot_size(self, context):
        """The order's instrument's lot at the broker the plan's orders go to.

        Args:
            context (OrderContext): The order's view of the plan order.

        Returns:
            int: The lot, at least one.
        """
        broker_name = context.chosen_broker()
        instrument, _, _ = context.placement.market_context(context.instrument_id, False, False)
        handle = instrument.handles.get(broker_name) or {}
        try:
            size = int(float(handle.get('lot_size') or 1))
        except (TypeError, ValueError):
            size = 1
        return max(size, 1)

    def scaled(self, context, filled):
        """The size for what the first plan has filled.

        Args:
            context (OrderContext): The order's view of the plan order.
            filled (int): What the first plan has filled.

        Returns:
            int: The size.
        """
        wanted = self.ratio * decimal.Decimal(filled)
        if not self.whole_lots:
            return int(wanted.to_integral_value(rounding=decimal.ROUND_HALF_UP))
        lot = self.lot_size(context)
        lots = (wanted / lot).to_integral_value(rounding=decimal.ROUND_HALF_UP)
        return int(lots) * lot

    def described(self):
        """This sizing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'parent_fill': {
                'ratio': str(self.ratio),
                'whole_lots': self.whole_lots,
            },
        }
