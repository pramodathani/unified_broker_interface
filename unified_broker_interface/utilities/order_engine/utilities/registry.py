"""The synthetic order types, by the name a caller's `synthetic.type` selects them with."""

from unified_broker_interface.utilities.order_engine.simple import SimpleOrder

SYNTHETIC_ORDER_CLASSES = {
    SimpleOrder.SYNTHETIC_TYPE: SimpleOrder,
}
