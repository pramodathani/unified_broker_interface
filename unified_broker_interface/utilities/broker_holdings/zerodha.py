"""
Zerodha (Kite) holdings, from `GET https://api.kite.trade/portfolio/holdings`.

The API client unwraps Kite's `data`, a list with one row per holding. A row names its instrument by
`instrument_token` - globally unique at Kite, and what unified.broker_mappings stores - on the
`exchange` it was bought on, with the ISIN beside it.

Kite splits the quantity: `quantity` is settled, `t1_quantity` bought and not yet settled, and `mtf`
holds what the margin trading facility funds, with its own average price. The holding is all three.
`last_price` and `close_price`, the previous close, are Kite's own.

A dead session is refused with HTTP 403 and `error_type` `TokenException`.
"""

from unified_broker_interface.utilities.broker_holdings.base import (BrokerHoldingsSource, HoldingsUnavailable,
                                                                     canonical_exchange, holding)
from unified_broker_interface.utilities.broker_funds.base import number

HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"

class ZerodhaHoldingsSource(BrokerHoldingsSource):
    """
    Reads Zerodha holdings.
    """

    BROKER_NAME = "zerodha"

    def fetch(self, client):
        data = (client.get(url=HOLDINGS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if not isinstance(data, list):
            raise HoldingsUnavailable(f"Kite answered the holdings request without holdings: {str(data)[:200]}")
        return data

    def normalize(self, data):
        holdings = []
        for row in data:
            if not isinstance(row, dict):
                continue
            mtf = row.get("mtf") or {}
            settled = number(row.get("quantity")) + number(row.get("t1_quantity"))
            average = number(row.get("average_price"))
            holdings.append(holding(
                broker_token=row.get("instrument_token"),
                exchange=canonical_exchange(row.get("exchange")),
                isin=row.get("isin"),
                symbol=row.get("tradingsymbol"),
                quantity=settled + number(mtf.get("quantity")),
                invested_value=settled * average + number(mtf.get("quantity")) * number(mtf.get("average_price")),
                collateral_quantity=row.get("collateral_quantity"),
                last_price=row.get("last_price"),
                close_price=row.get("close_price"),
            ))
        return holdings

    def is_authentication_error(self, exception):
        return getattr(exception, "code", None) == "TokenException"
