"""Shoonya's margin calculator, on the Noren platform."""

from unified_broker_interface.utilities.broker_orders.shoonya import ShoonyaOrders
from unified_broker_interface.utilities.margin_calculators.noren import (
    NorenMarginCalculator,
)


class ShoonyaMarginCalculator(NorenMarginCalculator):
    """Asks Shoonya's Noren server what an order, or a basket, needs."""

    BROKER_NAME = 'shoonya'
    ORDER_CLASS = ShoonyaOrders
