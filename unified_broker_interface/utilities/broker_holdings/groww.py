"""
Groww holdings, from `GET https://api.groww.in/v1/holdings/user`.

The API client unwraps Groww's `payload`, whose `holdings` is a list with one row per holding. Groww sends
no token for the instrument - only the ISIN, the `trading_symbol` and `tradable_exchanges`, NSE first - so
a holding is resolved by its symbol on the first tradable exchange. `quantity` is everything held: measured
on 2026-09-13 it was 7 where `demat_free_quantity` was 6 and `t1_quantity` 1. There is no price.

A dead session is refused with HTTP 401. Groww's 403 means the account is not entitled to an endpoint and a
login does nothing for it, so it is not taken for a session problem.
"""

from unified_broker_interface.utilities.broker_holdings.base import (BrokerHoldingsSource, HoldingsUnavailable,
                                                                     canonical_exchange, holding)
from unified_broker_interface.utilities.broker_funds.base import number

HOLDINGS_URL = "https://api.groww.in/v1/holdings/user"

_AUTHENTICATION_MARKERS = ("unauthori", "authentication", "token expired", "invalid token", "expired token", "jwt")

class GrowwHoldingsSource(BrokerHoldingsSource):
    """
    Reads Groww holdings.
    """

    BROKER_NAME = "groww"

    def fetch(self, client):
        data = (client.get(url=HOLDINGS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("holdings", []), list):
            raise HoldingsUnavailable(f"Groww answered the holdings request without holdings: {str(data)[:200]}")
        return data.get("holdings") or []

    def normalize(self, data):
        holdings = []
        for row in data:
            if not isinstance(row, dict):
                continue
            quantity = number(row.get("quantity"))
            holdings.append(holding(
                exchange=canonical_exchange((row.get("tradable_exchanges") or [None])[0]),
                isin=row.get("isin"),
                symbol=row.get("trading_symbol"),
                quantity=quantity,
                invested_value=quantity * number(row.get("average_price")),
                collateral_quantity=row.get("pledge_quantity"),
            ))
        return holdings

    def is_authentication_error(self, exception):
        status = str(getattr(exception, "code", "") or "").strip()
        lowered = str(exception).lower()
        if status in ("403", "429") or "access forbidden" in lowered:
            return False
        return status == "401" or any(marker in lowered for marker in _AUTHENTICATION_MARKERS)
