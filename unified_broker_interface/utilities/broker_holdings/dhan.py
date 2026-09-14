"""
Dhan holdings, from `GET https://api.dhan.co/v2/holdings`.

The API client passes Dhan's list through. A row names its instrument by `securityId`, which
unified.broker_mappings stores, with the ISIN beside it. `exchange` is `NSE` or `BSE`, or `ALL` for a
stock held on both, which names no exchange - the security id is then looked up on NSE, then BSE.

`totalQty` is everything held: measured on 2026-09-13 it was 8 where `dpQty` was 7 and `t1Qty` 1.
`lastTradedPrice` is Dhan's own.

An account holding nothing is refused with DH-1111 "No holdings available", which is an empty answer. A
dead session is refused with `errorType` `Invalid_Authentication` and code DH-901.
"""

from unified_broker_interface.utilities.broker_holdings.base import (BrokerHoldingsSource, HoldingsUnavailable,
                                                                     canonical_exchange, holding)
from unified_broker_interface.utilities.broker_funds.base import number

HOLDINGS_URL = "https://api.dhan.co/v2/holdings"

_NO_HOLDINGS_MARKERS = ("dh-1111", "no holding")

class DhanHoldingsSource(BrokerHoldingsSource):
    """
    Reads Dhan holdings.
    """

    BROKER_NAME = "dhan"

    def fetch(self, client):
        try:
            data = (client.get(url=HOLDINGS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        except Exception as exception:
            if any(marker in str(exception).lower() for marker in _NO_HOLDINGS_MARKERS):
                return []
            raise
        if not isinstance(data, list):
            raise HoldingsUnavailable(f"Dhan answered the holdings request without holdings: {str(data)[:200]}")
        return data

    def normalize(self, data):
        holdings = []
        for row in data:
            if not isinstance(row, dict):
                continue
            quantity = number(row.get("totalQty"))
            holdings.append(holding(
                broker_token=row.get("securityId"),
                exchange=canonical_exchange(row.get("exchange")),
                isin=row.get("isin"),
                symbol=row.get("tradingSymbol"),
                quantity=quantity,
                invested_value=quantity * number(row.get("avgCostPrice")),
                collateral_quantity=row.get("collateralQty"),
                last_price=row.get("lastTradedPrice"),
            ))
        return holdings

    def is_authentication_error(self, exception):
        code = str(getattr(exception, "code", "") or "").lower()
        return code == "invalid_authentication" or "dh-901" in str(exception).lower()
