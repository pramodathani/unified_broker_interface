"""
Wisdom Capital holdings, from Symphony XTS's `GET https://trade.wisdomcapital.in/interactive/portfolio/holdings`.

The request names the account as `clientID`, the `ucc_code` in Wisdom Capital's settings, on the
interactive session the API client carries, and the client unwraps XTS's `result`. Its
`RMSHoldings.Holdings` is an object keyed by ISIN rather than a list. Each entry carries the stock's
instrument id on both exchanges, `ExchangeNSEInstrumentId` and `ExchangeBSEInstrumentId`, zero where it is
not listed; the holding is resolved on NSE's when there is one and BSE's otherwise. `HoldingQuantity` is
the quantity, `BuyAvgPrice` the average price, and the pledged quantity is `CollateralQuantity` or
`PledgeQuantity`. There is no price.

A dead session is refused with an XTS `e-session` or `e-token` code, or "Invalid Token".
"""

from unified_broker_interface.utilities.broker_holdings.base import BrokerHoldingsSource, HoldingsUnavailable, holding
from unified_broker_interface.utilities.broker_funds.base import number

HOLDINGS_URL = "https://trade.wisdomcapital.in/interactive/portfolio/holdings"

_AUTHENTICATION_MARKERS = ("e-session", "e-token", "invalid token")

class WisdomCapitalHoldingsSource(BrokerHoldingsSource):
    """
    Reads Wisdom Capital holdings.
    """

    BROKER_NAME = "wisdom_capital"

    def fetch(self, client):
        response = client.get(url=HOLDINGS_URL, params={"clientID": client._settings.get("ucc_code", "")},
                              timeout=self.TIMEOUT_SECONDS)
        data = (response or {}).get("data")
        if not isinstance(data, dict):
            raise HoldingsUnavailable(f"XTS answered the holdings request without holdings: {str(data)[:200]}")
        holdings = (data.get("RMSHoldings") or {}).get("Holdings") or {}
        if not isinstance(holdings, dict):
            raise HoldingsUnavailable(f"XTS answered the holdings request without holdings: {str(data)[:200]}")
        return holdings

    def normalize(self, data):
        holdings = []
        for isin, row in data.items():
            if not isinstance(row, dict):
                continue
            nse = number(row.get("ExchangeNSEInstrumentId"))
            quantity = number(row.get("HoldingQuantity"))
            holdings.append(holding(
                broker_token=int(nse) if nse else int(number(row.get("ExchangeBSEInstrumentId"))),
                exchange="nse" if nse else "bse",
                isin=row.get("ISIN") or isin,
                symbol=row.get("Symbol"),
                quantity=quantity,
                invested_value=quantity * number(row.get("BuyAvgPrice")),
                collateral_quantity=row.get("CollateralQuantity") or row.get("PledgeQuantity"),
            ))
        return holdings

    def is_authentication_error(self, exception):
        text = f"{getattr(exception, 'code', '')} {getattr(exception, 'message', '')} {exception}".lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
