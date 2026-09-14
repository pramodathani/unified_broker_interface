"""
Kotak Neo funds, from `POST {base_url}/quick/user/limits`.

`base_url` is the host Kotak assigned the session at login, which the API client reads from the stored
login. The body must be the Noren-style form `jData={"seg":"ALL","exch":"ALL","prod":"ALL"}` - the plain
JSON and form bodies Kotak's documentation shows are answered with a 500. The request is made here rather
than through the API client, because the client drops `timeout`, with the session's `Auth` and `Sid`.

Kotak returns about eighty flat fields covering every segment and product at once. The available balance
is stated, as `Net`; beside it are the collateral, adhoc margin, margin used, the SPAN and exposure margin
now blocked, the realised and unrealised mark to market and the day's pay-in and payout. The segments carry
the commodity, derivatives and currency SPAN and exposure margins, each the normal and intraday products
together - Kotak's own field names, including the `FoSpanrgn` spelling.

A dead session is refused with HTTP 401 and "unauthorised".
"""

import json

import requests

from stock_brokers.api.kotak import KotakAPIException
from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  add_segment, funds_record, number)

LIMITS_PATH = "/quick/user/limits"

LIMITS_BODY = "jData=" + json.dumps({"seg": "ALL", "exch": "ALL", "prod": "ALL"})

# Each segment's SPAN and exposure fields, each summed over Kotak's normal and intraday products.
SEGMENT_FIELDS = {
    "commodity": ("ComSpanMrgn{}Prsnt", "ComExpsrMrgn{}Prsnt"),
    "derivatives": ("FoSpanrgn{}Prsnt", "FoExpMrgn{}Prsnt"),
    "currency": ("CurSpanMrgn{}Prsnt", "CurExpMrgn{}Prsnt"),
}

PRODUCTS = ("Nrml", "Mis")

_AUTHENTICATION_MARKERS = ("unauthorised", "unauthorized", "invalid session", "session expired")

class KotakFundsSource(BrokerFundsSource):
    """
    Reads Kotak funds.
    """

    BROKER_NAME = "kotak"

    def fetch(self, client):
        login = client._current_login() or {}
        headers = {"neo-fin-key": "neotradeapi", "Auth": str(login.get("access_token")), "Sid": str(login.get("sid"))}
        response = requests.post(client.url(LIMITS_PATH), data=LIMITS_BODY, headers=headers,
                                 timeout=self.TIMEOUT_SECONDS)
        if response.status_code >= 300:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        try:
            data = response.json()
        except ValueError:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        if not isinstance(data, dict):
            raise FundsUnavailable(f"Kotak answered the limits request without limits: {str(data)[:200]}")
        if data.get("stat") not in (None, "Ok"):
            message = str(data.get("emsg") or data.get("errMsg") or data)
            raise KotakAPIException(code=data.get("stCode"), message=message[:300])
        return data

    def normalize(self, data):
        record = funds_record()
        add(record, "summary", "available_balance", data.get("Net"))
        add(record, "summary", "collateral_value", data.get("CollateralValue"))
        add(record, "summary", "adhoc_credit", data.get("AdhocMargin"))
        add(record, "summary", "margin_utilized", data.get("MarginUsed"))
        add(record, "margin_breakdown", "span_margin", data.get("SpanMarginPrsnt"))
        add(record, "margin_breakdown", "exposure_margin", data.get("ExposureMarginPrsnt"))
        add(record, "pnl", "realized", data.get("RealizedMtomPrsnt"))
        add(record, "pnl", "unrealized", data.get("UnrealizedMtomPrsnt"))
        add(record, "cash_movement", "pay_in_today", data.get("RmsPayInAmt"))
        add(record, "cash_movement", "pay_out_today", data.get("RmsPayOutAmt"))

        for segment, (span, exposure) in SEGMENT_FIELDS.items():
            add_segment(record, segment,
                        span_margin=sum(number(data.get(span.format(product))) for product in PRODUCTS),
                        exposure_margin=sum(number(data.get(exposure.format(product))) for product in PRODUCTS))
        return record

    def is_authentication_error(self, exception):
        if str(getattr(exception, "code", "")) == "401":
            return True
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
