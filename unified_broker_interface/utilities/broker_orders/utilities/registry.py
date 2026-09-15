"""The broker order classes, in the order the brokers take turns."""

from unified_broker_interface.utilities.broker_orders.dhan import DhanOrders
from unified_broker_interface.utilities.broker_orders.flattrade import (
    FlattradeOrders,
)
from unified_broker_interface.utilities.broker_orders.fyers import FyersOrders
from unified_broker_interface.utilities.broker_orders.groww import GrowwOrders
from unified_broker_interface.utilities.broker_orders.indmoney import (
    IndmoneyOrders,
)
from unified_broker_interface.utilities.broker_orders.kotak import KotakOrders
from unified_broker_interface.utilities.broker_orders.shoonya import (
    ShoonyaOrders,
)
from unified_broker_interface.utilities.broker_orders.stoxkart import (
    StoxkartOrders,
)
from unified_broker_interface.utilities.broker_orders.wisdom_capital import (
    WisdomCapitalOrders,
)
from unified_broker_interface.utilities.broker_orders.zerodha import (
    ZerodhaOrders,
)

BROKER_ORDER_CLASSES = [
    DhanOrders,
    FlattradeOrders,
    FyersOrders,
    GrowwOrders,
    IndmoneyOrders,
    KotakOrders,
    ShoonyaOrders,
    StoxkartOrders,
    WisdomCapitalOrders,
    ZerodhaOrders,
]
