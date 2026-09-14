"""
Funds from brokers on the Noren platform, Flattrade and Shoonya, from `Limits`.

**The request.** `Limits` is a POST whose body is `jData={"uid":...,"actid":...}&jKey=...`; the API client
adds `uid` and `jKey` and does the wrapping, so only the account is named here, and a subclass says which
settings field holds it.

**The response.** Noren answers HTTP 200 whether or not it served the request, with `stat` `Ok` or
`Not_Ok`, so the body is inspected: a dead session is raised as `NorenRefusal`, which
`is_authentication_error` recognises, and any other refusal as `FundsUnavailable`.

Noren states no single available figure, so it is derived as cash plus collateral plus the day's cash,
less the margin used. Most other fields - SPAN, exposure, margin used, collateral, realised and
unrealised profit - are sent only once a segment has had activity, and an idle account's response omits
them, which reads as zero. Collateral is `collateral` where present and the broker collateral amount
`brkcollamt` otherwise. The per-segment margins come from the segment-suffixed fields,
`span_{e,d,f,c}_{i,m,c}` and `expo_...` - equity, derivatives, currency and commodity, each for the
intraday, margin and cash-and-carry products - and a segment is reported only when it has any.
"""

from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  add_segment, funds_record, number)

# What Noren says when the session key is no good, lowercased.
_AUTHENTICATION_MARKERS = ("session expired", "invalid session key", "invalid session")

# A segment's field suffix in `Limits`, for each segment name.
_SEGMENT_SUFFIXES = (("equity", "e"), ("derivatives", "d"), ("currency", "f"), ("commodity", "c"))

# The product suffixes a segment's margin fields are split by: intraday, margin and cash-and-carry.
_PRODUCT_SUFFIXES = ("i", "m", "c")

class NorenRefusal(Exception):
    """
    Noren refused the session in the body of an HTTP 200 response.
    """

class NorenFundsSource(BrokerFundsSource):
    """
    Reads funds from a Noren deployment. A subclass sets BROKER_NAME, LIMITS_URL and ACCOUNT_FIELD.

    Attributes:
        LIMITS_URL (str): The deployment's `Limits` endpoint.
        ACCOUNT_FIELD (str): The `settings` field holding the account id sent as `actid`.
    """

    LIMITS_URL = None
    ACCOUNT_FIELD = None

    def fetch(self, client):
        # A fresh dict each time: the API client writes the user id into the one it is given.
        response = client.post(url=self.LIMITS_URL, data={"actid": client._settings[self.ACCOUNT_FIELD]},
                               timeout=self.TIMEOUT_SECONDS)
        data = (response or {}).get("data")
        if not isinstance(data, dict):
            raise FundsUnavailable(f"{self.BROKER_NAME} answered the limits request without limits: {str(data)[:200]}")
        if str(data.get("stat", "")).lower() != "ok":
            message = str(data.get("emsg") or data)
            if any(marker in message.lower() for marker in _AUTHENTICATION_MARKERS):
                raise NorenRefusal(f"{self.BROKER_NAME} refused the session: {message[:200]}")
            raise FundsUnavailable(f"{self.BROKER_NAME} refused the limits request: {message[:200]}")
        return data

    def normalize(self, data):
        record = funds_record()
        collateral = data.get("collateral", data.get("brkcollamt"))
        add(record, "summary", "available_balance", number(data.get("cash")) + number(collateral)
            + number(data.get("daycash")) - number(data.get("marginused")))
        add(record, "summary", "cash_balance", data.get("cash"))
        add(record, "summary", "collateral_value", collateral)
        add(record, "summary", "adhoc_credit", data.get("daycash"))
        add(record, "summary", "margin_utilized", data.get("marginused"))
        add(record, "margin_breakdown", "span_margin", data.get("span"))
        add(record, "margin_breakdown", "exposure_margin", data.get("expo"))
        add(record, "margin_breakdown", "other_margin", number(data.get("premium")) + number(data.get("varelm"))
            + number(data.get("marprt")))
        add(record, "pnl", "realized", data.get("rpnl"))
        add(record, "pnl", "unrealized", data.get("unmtom"))
        add(record, "cash_movement", "pay_in_today", data.get("payin"))
        add(record, "cash_movement", "pay_out_today", data.get("payout"))
        add(record, "cash_movement", "uncleared_funds", data.get("unclearedcash"))

        for segment, suffix in _SEGMENT_SUFFIXES:
            span = sum(number(data.get(f"span_{suffix}_{product}")) for product in _PRODUCT_SUFFIXES)
            exposure = sum(number(data.get(f"expo_{suffix}_{product}")) for product in _PRODUCT_SUFFIXES)
            if span or exposure:
                add_segment(record, segment, span_margin=span, exposure_margin=exposure)
        return record

    def is_authentication_error(self, exception):
        if isinstance(exception, NorenRefusal):
            return True
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
