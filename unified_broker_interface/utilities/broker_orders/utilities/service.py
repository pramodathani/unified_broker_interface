"""
The brokers' orders modules in service, which `utilities/write_service.py` places, modifies and cancels through.

Today's orders and trades for `/api/orders/details` and `/api/orders/trades` come from `unified:orders:orders` and
`unified:orders:trades`, which `bin/unified/orders` and `bin/unified/trades` keep; nothing here reads an order book
for them.
"""

from unified_broker_interface.utilities.broker_orders.dhan import DhanOrdersSource
from unified_broker_interface.utilities.broker_orders.flattrade import FlattradeOrdersSource
from unified_broker_interface.utilities.broker_orders.fyers import FyersOrdersSource
from unified_broker_interface.utilities.broker_orders.groww import GrowwOrdersSource
from unified_broker_interface.utilities.broker_orders.indmoney import IndmoneyOrdersSource
from unified_broker_interface.utilities.broker_orders.kotak import KotakOrdersSource
from unified_broker_interface.utilities.broker_orders.shoonya import ShoonyaOrdersSource
from unified_broker_interface.utilities.broker_orders.stoxkart import StoxkartOrdersSource
from unified_broker_interface.utilities.broker_orders.wisdom_capital import WisdomCapitalOrdersSource
from unified_broker_interface.utilities.broker_orders.zerodha import ZerodhaOrdersSource

# Brokers whose orders module is in service.
SOURCES = {source.BROKER_NAME: source() for source in (ZerodhaOrdersSource, DhanOrdersSource, FlattradeOrdersSource,
                                                        FyersOrdersSource, GrowwOrdersSource, IndmoneyOrdersSource,
                                                        KotakOrdersSource, ShoonyaOrdersSource, StoxkartOrdersSource,
                                                        WisdomCapitalOrdersSource)}
