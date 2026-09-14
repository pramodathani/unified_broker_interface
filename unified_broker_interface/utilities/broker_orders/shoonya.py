"""
Shoonya orders and trades, from `POST https://api.shoonya.com/NorenWClientAPI/OrderBook` and `TradeBook`.

Shoonya is Finvasia's Noren deployment, so the requests, the rows and the refusals are all `NorenOrdersSource`'s;
see `utilities/noren.py`. The account is the `ucc_code` in Shoonya's settings.
"""

from unified_broker_interface.utilities.broker_orders.utilities.noren import NorenOrdersSource

class ShoonyaOrdersSource(NorenOrdersSource):
    """
    Reads Shoonya orders and trades.
    """

    BROKER_NAME = "shoonya"
    BASE_URL = "https://api.shoonya.com/NorenWClientAPI"
    ACCOUNT_FIELD = "ucc_code"
