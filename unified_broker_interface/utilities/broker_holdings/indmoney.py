"""
INDmoney (INDstocks) holdings, from `GET https://api.indstocks.com/portfolio/holdings`.

The API client unwraps INDstocks' `data`, a list with one row per holding. A row names its instrument by
`security_id`, which unified.broker_mappings stores, with the ISIN beside it, but names no exchange; the
security id is NSE's, so it is looked up on NSE. `total_qty` is everything held: measured on 2026-09-13 it
was 6 where `dp_qty` and `t1_qty` were 3 each. `used_qty` is the quantity pledged. There is no price.

A dead session is refused with a message asking to re-authenticate or naming the access token.
"""

from unified_broker_interface.utilities.broker_holdings.base import BrokerHoldingsSource, HoldingsUnavailable, holding
from unified_broker_interface.utilities.broker_funds.base import number

HOLDINGS_URL = "https://api.indstocks.com/portfolio/holdings"

_AUTHENTICATION_MARKERS = ("access_token", "re-authenticate", "unauthorized")

class IndmoneyHoldingsSource(BrokerHoldingsSource):
    """
    Reads INDmoney holdings.
    """

    BROKER_NAME = "indmoney"

    def fetch(self, client):
        data = (client.get(url=HOLDINGS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if data in (None, {}):
            return []
        if not isinstance(data, list):
            raise HoldingsUnavailable(f"INDstocks answered the holdings request without holdings: {str(data)[:200]}")
        return data

    def normalize(self, data):
        holdings = []
        for row in data:
            if not isinstance(row, dict):
                continue
            quantity = number(row.get("total_qty"))
            holdings.append(holding(
                broker_token=row.get("security_id"),
                exchange="nse",
                isin=row.get("isin"),
                symbol=row.get("symbol"),
                quantity=quantity,
                invested_value=quantity * number(row.get("avg_price")),
                collateral_quantity=row.get("used_qty"),
            ))
        return holdings

    def is_authentication_error(self, exception):
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
