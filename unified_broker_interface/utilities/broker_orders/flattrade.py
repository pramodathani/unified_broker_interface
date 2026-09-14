"""
Flattrade orders and trades, from `POST https://piconnect.flattrade.in/PiConnectAPI/OrderBook` and `TradeBook`.

Flattrade runs on Noren, so the requests, the rows and the refusals are all `NorenOrdersSource`'s; see
`utilities/noren.py`. The account is the `username` in Flattrade's settings.
"""

from unified_broker_interface.utilities.broker_orders.utilities.noren import NorenOrdersSource

class FlattradeOrdersSource(NorenOrdersSource):
    """
    Reads Flattrade orders and trades.
    """

    BROKER_NAME = "flattrade"
    BASE_URL = "https://piconnect.flattrade.in/PiConnectAPI"
    ACCOUNT_FIELD = "username"
