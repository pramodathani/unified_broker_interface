"""
Wisdom Capital funds, from Symphony XTS's `GET https://trade.wisdomcapital.in/interactive/user/balance`.

The request names the account as `clientID`, the `ucc_code` in Wisdom Capital's settings, and goes on the
interactive (trading) session the API client carries - not the market data session quotes use. The API
client unwraps XTS's `result`.

The answer is `BalanceList`, one entry per limit header; this account has one, `ALL|ALL|ALL`, a single
pool, so nothing goes into the segments. Its `limitObject` holds `RMSSubLimits` - the stated
`netMarginAvailable`, the cash, collateral, margin utilized and realised and unrealised mark to market -
`marginAvailable`, with the adhoc margin and the day's pay-in and payout, and `marginUtilized`, with the
SPAN, exposure, VaR and extreme loss, and scrip basket margins. Wisdom Capital sends some of these as the
string "NaN", which reads as zero.

A dead session is refused with an XTS `e-session` or `e-token` code, or "Invalid Token".
"""

from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  funds_record, number)

BALANCE_URL = "https://trade.wisdomcapital.in/interactive/user/balance"

_AUTHENTICATION_MARKERS = ("e-session", "e-token", "invalid token")

class WisdomCapitalFundsSource(BrokerFundsSource):
    """
    Reads Wisdom Capital funds.
    """

    BROKER_NAME = "wisdom_capital"

    def fetch(self, client):
        response = client.get(url=BALANCE_URL, params={"clientID": client._settings.get("ucc_code", "")},
                              timeout=self.TIMEOUT_SECONDS)
        data = (response or {}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("BalanceList"), list):
            raise FundsUnavailable(f"XTS answered the balance request without balances: {str(data)[:200]}")
        return data

    def normalize(self, data):
        record = funds_record()
        balances = data.get("BalanceList") or []
        limits = ((balances[0] if balances and isinstance(balances[0], dict) else {}).get("limitObject")) or {}
        sub_limits = limits.get("RMSSubLimits") or {}
        available = limits.get("marginAvailable") or {}
        utilized = limits.get("marginUtilized") or {}

        add(record, "summary", "available_balance", sub_limits.get("netMarginAvailable"))
        add(record, "summary", "cash_balance", sub_limits.get("cashAvailable"))
        add(record, "summary", "collateral_value", sub_limits.get("collateral"))
        add(record, "summary", "margin_utilized", sub_limits.get("marginUtilized"))
        add(record, "summary", "adhoc_credit", available.get("AdhocMargin"))
        add(record, "pnl", "realized", sub_limits.get("RealizedMTM"))
        add(record, "pnl", "unrealized", sub_limits.get("UnrealizedMTM"))
        add(record, "cash_movement", "pay_in_today", available.get("PayInAmount"))
        add(record, "cash_movement", "pay_out_today", available.get("PayOutAmount"))
        add(record, "margin_breakdown", "span_margin", utilized.get("TotalSpanMargin"))
        add(record, "margin_breakdown", "exposure_margin", utilized.get("ExposureMarginPresent"))
        add(record, "margin_breakdown", "other_margin", number(utilized.get("VarELMarginPresent"))
            + number(utilized.get("ScripBasketMarginPresent")))
        return record

    def is_authentication_error(self, exception):
        text = f"{getattr(exception, 'code', '')} {getattr(exception, 'message', '')} {exception}".lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
