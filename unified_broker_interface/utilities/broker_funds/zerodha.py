"""
Zerodha (Kite) funds, from `GET https://api.kite.trade/user/margins`.

Kite answers with an `equity` and a `commodity` block, and the API client unwraps its `data` envelope.
Each block states its own `net` - what can back a new order in that segment - so the available balance
is read, not derived, and the account's is the sum of the two. Under `available` a block carries the
cash, collateral, adhoc margin and the day's pay-in; under `utilised`, the margin blocked (`debits`), its
SPAN and exposure parts, the realised and unrealised mark to market, and the day's payout.

A dead session is refused with HTTP 403 and `error_type` `TokenException`, which the API client raises as
the exception's `code`.
"""

from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  add_segment, funds_record)

MARGINS_URL = "https://api.kite.trade/user/margins"

SEGMENTS = ("equity", "commodity")

class ZerodhaFundsSource(BrokerFundsSource):
    """
    Reads Zerodha funds.
    """

    BROKER_NAME = "zerodha"

    def fetch(self, client):
        data = client.get(url=MARGINS_URL, timeout=self.TIMEOUT_SECONDS).get("data")
        if not isinstance(data, dict):
            raise FundsUnavailable(f"Kite answered the margins request without margins: {str(data)[:200]}")
        return data

    def normalize(self, data):
        record = funds_record()
        for segment in SEGMENTS:
            block = data.get(segment) or {}
            available = block.get("available") or {}
            utilised = block.get("utilised") or {}

            add(record, "summary", "available_balance", block.get("net"))
            add(record, "summary", "cash_balance", available.get("cash"))
            add(record, "summary", "collateral_value", available.get("collateral"))
            add(record, "summary", "adhoc_credit", available.get("adhoc_margin"))
            add(record, "summary", "margin_utilized", utilised.get("debits"))
            add(record, "margin_breakdown", "span_margin", utilised.get("span"))
            add(record, "margin_breakdown", "exposure_margin", utilised.get("exposure"))
            add(record, "pnl", "realized", utilised.get("m2m_realised"))
            add(record, "pnl", "unrealized", utilised.get("m2m_unrealised"))
            add(record, "cash_movement", "pay_in_today", available.get("intraday_payin"))
            add(record, "cash_movement", "pay_out_today", utilised.get("payout"))

            add_segment(record, segment,
                        available_balance=block.get("net"),
                        margin_utilized=utilised.get("debits"),
                        span_margin=utilised.get("span"),
                        exposure_margin=utilised.get("exposure"))
        return record

    def is_authentication_error(self, exception):
        return getattr(exception, "code", None) == "TokenException"
