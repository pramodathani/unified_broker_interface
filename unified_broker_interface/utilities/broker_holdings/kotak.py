"""
Kotak Neo holdings, from `GET {base_url}/portfolio/v1/holdings`.

`base_url` is the host Kotak assigned the session at login, which the API client reads from the stored
login. The request is made here rather than through the API client, because the client drops `timeout`,
with the session's `Auth` and `Sid`.

The answer's `data` is a list with one row per holding. A row names its instrument by `exchangeIdentifier`
- the exchange token unified.broker_mappings stores; `instrumentToken` beside it is Kotak's own and
maps to nothing - on the exchange its `exchangeSegment` names, `nse_cm` or `bse_cm`. Kotak sends no ISIN,
so a holding joins another broker's row only once its token resolves. `closingPrice` is the previous
close; there is no last price.

A dead session is refused with HTTP 401 and "unauthorised".
"""

import requests

from stock_brokers.api.kotak import KotakAPIException
from unified_broker_interface.utilities.broker_holdings.base import (BrokerHoldingsSource, HoldingsUnavailable,
                                                                     canonical_exchange, holding)
from unified_broker_interface.utilities.broker_funds.base import number

HOLDINGS_PATH = "/portfolio/v1/holdings"

_AUTHENTICATION_MARKERS = ("unauthorised", "unauthorized", "invalid session", "session expired")

class KotakHoldingsSource(BrokerHoldingsSource):
    """
    Reads Kotak holdings.
    """

    BROKER_NAME = "kotak"

    def fetch(self, client):
        login = client._current_login() or {}
        headers = {"neo-fin-key": "neotradeapi", "Auth": str(login.get("access_token")), "Sid": str(login.get("sid"))}
        response = requests.get(client.url(HOLDINGS_PATH), headers=headers, timeout=self.TIMEOUT_SECONDS)
        if response.status_code >= 300:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        try:
            payload = response.json()
        except ValueError:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        data = payload.get("data") if isinstance(payload, dict) else payload
        if data in (None, {}):
            return []
        if not isinstance(data, list):
            raise HoldingsUnavailable(f"Kotak answered the holdings request without holdings: {str(payload)[:200]}")
        return data

    def normalize(self, data):
        holdings = []
        for row in data:
            if not isinstance(row, dict):
                continue
            quantity = number(row.get("quantity"))
            holdings.append(holding(
                broker_token=row.get("exchangeIdentifier"),
                exchange=canonical_exchange(row.get("exchangeSegment")),
                symbol=row.get("symbol"),
                quantity=quantity,
                invested_value=quantity * number(row.get("averagePrice")),
                close_price=row.get("closingPrice"),
            ))
        return holdings

    def is_authentication_error(self, exception):
        if str(getattr(exception, "code", "")) == "401":
            return True
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
