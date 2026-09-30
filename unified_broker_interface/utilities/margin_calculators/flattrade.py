"""Flattrade's margin calculator, on the Noren platform."""

from unified_broker_interface.utilities.broker_orders.flattrade import FlattradeOrders
from unified_broker_interface.utilities.margin_calculators.noren import (
    NorenMarginCalculator,
)


class FlattradeMarginCalculator(NorenMarginCalculator):
    """Asks Flattrade's Noren server what an order, or a basket, needs."""

    BROKER_NAME = 'flattrade'
    ORDER_CLASS = FlattradeOrders
