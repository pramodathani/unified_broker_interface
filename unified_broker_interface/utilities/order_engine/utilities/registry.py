"""The synthetic order types the engine runs with classes of their own, by the name a caller's `synthetic.type` selects them with."""

from unified_broker_interface.utilities.order_engine.plan import PlanOrder
from unified_broker_interface.utilities.order_engine.simple import SimpleOrder

SYNTHETIC_ORDER_CLASSES = {
    SimpleOrder.SYNTHETIC_TYPE: SimpleOrder,
    PlanOrder.SYNTHETIC_TYPE: PlanOrder,
}
