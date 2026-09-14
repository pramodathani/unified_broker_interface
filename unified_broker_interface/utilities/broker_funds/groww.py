"""
Groww funds, from `GET https://api.groww.in/v1/margins/detail/user`.

The API client unwraps Groww's `payload`. Groww states no single available figure for the account, so it
is derived as clear cash plus the collateral available plus the adhoc margin, less the net margin used;
the collateral value is the collateral used plus the collateral available. The realised and unrealised
profit are the commodity block's mark to market, the only profit figures Groww's margin detail carries.

The equity, derivatives and commodity blocks become the three segments: the equity balance is the
cash-and-carry and intraday balances together, the derivatives balance the future, option buy and option
sell balances, and the commodity block carries margins only - its margin used is the sum of its SPAN,
exposure, tender, special and additional margins.

A dead session is refused with HTTP 401. Groww's 403 means the account is not entitled to an endpoint and
a login does nothing for it, so it is not taken for a session problem.
"""

from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  add_segment, funds_record, number)

MARGIN_DETAIL_URL = "https://api.groww.in/v1/margins/detail/user"

_AUTHENTICATION_MARKERS = ("unauthori", "authentication", "token expired", "invalid token", "expired token", "jwt")

class GrowwFundsSource(BrokerFundsSource):
    """
    Reads Groww funds.
    """

    BROKER_NAME = "groww"

    def fetch(self, client):
        data = (client.get(url=MARGIN_DETAIL_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if not isinstance(data, dict):
            raise FundsUnavailable(f"Groww answered the margin detail request without margins: {str(data)[:200]}")
        return data

    def normalize(self, data):
        record = funds_record()
        derivatives = data.get("fno_margin_details") or {}
        equity = data.get("equity_margin_details") or {}
        commodity = data.get("commodity_margin_details") or {}

        add(record, "summary", "available_balance", number(data.get("clear_cash")) + number(data.get("collateral_available"))
            + number(data.get("adhoc_margin")) - number(data.get("net_margin_used")))
        add(record, "summary", "cash_balance", data.get("clear_cash"))
        add(record, "summary", "margin_utilized", data.get("net_margin_used"))
        add(record, "summary", "collateral_value", number(data.get("collateral_used")) + number(data.get("collateral_available")))
        add(record, "summary", "adhoc_credit", data.get("adhoc_margin"))
        add(record, "pnl", "realized", commodity.get("commodity_realised_m2m"))
        add(record, "pnl", "unrealized", commodity.get("commodity_unrealised_m2m"))

        add_segment(record, "equity",
                    available_balance=number(equity.get("cnc_balance_available")) + number(equity.get("mis_balance_available")),
                    margin_utilized=equity.get("net_equity_margin_used"))
        add_segment(record, "derivatives",
                    available_balance=number(derivatives.get("future_balance_available"))
                    + number(derivatives.get("option_buy_balance_available"))
                    + number(derivatives.get("option_sell_balance_available")),
                    margin_utilized=derivatives.get("net_fno_margin_used"),
                    span_margin=derivatives.get("span_margin_used"),
                    exposure_margin=derivatives.get("exposure_margin_used"))
        add_segment(record, "commodity",
                    margin_utilized=sum(number(commodity.get(f"commodity_{kind}_margin"))
                                        for kind in ("span", "exposure", "tender", "special", "additional")),
                    span_margin=commodity.get("commodity_span_margin"),
                    exposure_margin=commodity.get("commodity_exposure_margin"))
        return record

    def is_authentication_error(self, exception):
        status = str(getattr(exception, "code", "") or "").strip()
        lowered = str(exception).lower()
        if status in ("403", "429") or "access forbidden" in lowered:
            return False
        return status == "401" or any(marker in lowered for marker in _AUTHENTICATION_MARKERS)
