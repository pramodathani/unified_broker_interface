"""What every way of sizing an order from a Then join's fills shares: the lot at the chosen broker, and rounding to it."""

import decimal


class FillSizing:
    """The base of a Then join child's size worked out from what the first plan has filled.

    A subclass works out the wanted size in `scaled`; this class holds the lot lookup and the rounding they share, and a `check` that refuses nothing.

    Attributes:
        whole_lots (bool): Whether the size is rounded to the nearest whole lot.
    """

    def __init__(self, whole_lots):
        """Builds the sizing.

        Args:
            whole_lots (bool): Whether to round to whole lots.

        Returns:
            None: This method returns nothing.
        """
        self.whole_lots = whole_lots

    def check(self, context):
        """Checks the sizing can work for this order when the plan is placed, which by default it always can.

        Args:
            context (OrderContext): Unused.

        Returns:
            None: This method returns nothing.
        """
        del context

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

    def rounded(self, context, wanted):
        """A wanted size rounded to a whole number, or to whole lots when asked.

        Args:
            context (OrderContext): The order's view of the plan order.
            wanted (decimal.Decimal): The size before rounding.

        Returns:
            int: The size.
        """
        if not self.whole_lots:
            return int(wanted.to_integral_value(rounding=decimal.ROUND_HALF_UP))
        lot = self.lot_size(context)
        lots = (wanted / lot).to_integral_value(rounding=decimal.ROUND_HALF_UP)
        return int(lots) * lot
