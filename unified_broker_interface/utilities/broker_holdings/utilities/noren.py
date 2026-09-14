"""
Holdings from brokers on the Noren platform, Flattrade and Shoonya, from `Holdings`.

**The request.** `Holdings` is a POST whose body is `jData={"uid":...,"actid":...,"prd":"C"}&jKey=...`;
the API client adds `uid` and `jKey` and does the wrapping, so only the account and the cash-and-carry
product are named here, and a subclass says which settings field holds the account.

**The response.** A list with one row per holding. `exch_tsym` lists the stock's listings, NSE first, each
with its exchange, token, trading symbol and ISIN, and the first is the one the holding is resolved on.
The quantity is spread over several fields, and the holding is their sum: `holdqty`, authorised for
delivery; `npoadqty`, held but not authorised; and `npoadt1qty`, bought and not yet settled - measured on
2026-09-13 at Flattrade as 50 beside an `npoadqty` of 4, a field Shoonya's row did not carry. `upldprc` is
the average price. There is no last price; `c`, the previous close, is kept.

Noren answers HTTP 200 whether or not it served the request. An account holding nothing is a `Not_Ok`
saying "no data", which is an empty answer; a dead session is raised as `NorenRefusal`, which
`is_authentication_error` recognises; anything else is `HoldingsUnavailable`.
"""

from unified_broker_interface.utilities.broker_holdings.base import (BrokerHoldingsSource, HoldingsUnavailable,
                                                                     canonical_exchange, holding)
from unified_broker_interface.utilities.broker_funds.base import number

# What Noren says when the session key is no good, lowercased.
_AUTHENTICATION_MARKERS = ("session expired", "invalid session key", "invalid session")

# What Noren says when there is nothing to list, lowercased.
_NO_DATA_MARKER = "no data"

# The fields a holding's quantity is spread over.
_QUANTITY_FIELDS = ("holdqty", "npoadqty", "npoadt1qty")

class NorenRefusal(Exception):
    """
    Noren refused the session in the body of an HTTP 200 response.
    """

class NorenHoldingsSource(BrokerHoldingsSource):
    """
    Reads holdings from a Noren deployment. A subclass sets BROKER_NAME, HOLDINGS_URL and ACCOUNT_FIELD.

    Attributes:
        HOLDINGS_URL (str): The deployment's `Holdings` endpoint.
        ACCOUNT_FIELD (str): The `settings` field holding the account id sent as `actid`.
    """

    HOLDINGS_URL = None
    ACCOUNT_FIELD = None

    def fetch(self, client):
        # A fresh dict each time: the API client writes the user id into the one it is given.
        response = client.post(url=self.HOLDINGS_URL, data={"actid": client._settings[self.ACCOUNT_FIELD], "prd": "C"},
                               timeout=self.TIMEOUT_SECONDS)
        data = (response or {}).get("data")
        if isinstance(data, dict) and str(data.get("stat", "")).lower() != "ok":
            message = str(data.get("emsg") or data)
            if _NO_DATA_MARKER in message.lower():
                return []
            if any(marker in message.lower() for marker in _AUTHENTICATION_MARKERS):
                raise NorenRefusal(f"{self.BROKER_NAME} refused the session: {message[:200]}")
            raise HoldingsUnavailable(f"{self.BROKER_NAME} refused the holdings request: {message[:200]}")
        if not isinstance(data, list):
            raise HoldingsUnavailable(f"{self.BROKER_NAME} answered the holdings request without holdings: {str(data)[:200]}")
        return data

    def normalize(self, data):
        holdings = []
        for row in data:
            if not isinstance(row, dict):
                continue
            listing = (row.get("exch_tsym") or [{}])[0] or {}
            quantity = sum(number(row.get(field)) for field in _QUANTITY_FIELDS)
            holdings.append(holding(
                broker_token=listing.get("token"),
                exchange=canonical_exchange(listing.get("exch")),
                isin=listing.get("isin"),
                symbol=listing.get("tsym"),
                quantity=quantity,
                invested_value=quantity * number(row.get("upldprc")),
                collateral_quantity=row.get("colqty"),
                close_price=row.get("c"),
            ))
        return holdings

    def is_authentication_error(self, exception):
        if isinstance(exception, NorenRefusal):
            return True
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
