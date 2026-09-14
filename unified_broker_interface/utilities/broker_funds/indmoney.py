"""
INDmoney (INDstocks) funds, from `GET https://api.indstocks.com/funds`.

The API client unwraps INDstocks' `data`. INDstocks states no single available figure, so it is derived as
the start of day balance plus the pledge received, which is also the collateral; the start of day balance
is the cash. Beside them are the withdrawable balance, the day's funds added and withdrawn, and the
realised and unrealised profit.

`detailed_avl_balance` breaks the balance down by product, and those become the segments: the equity
balance is the cash-and-carry, intraday and margin trading balances together, the derivatives balance the
future, option buy and option sell balances, and the commodity balance the commodity option buy balance.

A dead session is refused with a message asking to re-authenticate or naming the access token.
"""

from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  add_segment, funds_record, number)

FUNDS_URL = "https://api.indstocks.com/funds"

_AUTHENTICATION_MARKERS = ("access_token", "re-authenticate", "unauthorized")

class IndmoneyFundsSource(BrokerFundsSource):
    """
    Reads INDmoney funds.
    """

    BROKER_NAME = "indmoney"

    def fetch(self, client):
        data = (client.get(url=FUNDS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if not isinstance(data, dict):
            raise FundsUnavailable(f"INDstocks answered the funds request without funds: {str(data)[:200]}")
        return data

    def normalize(self, data):
        record = funds_record()
        detail = data.get("detailed_avl_balance") or {}

        add(record, "summary", "available_balance", number(data.get("sod_balance")) + number(data.get("pledge_received")))
        add(record, "summary", "cash_balance", data.get("sod_balance"))
        add(record, "summary", "collateral_value", data.get("pledge_received"))
        add(record, "summary", "withdrawable_balance", data.get("withdrawal_balance"))
        add(record, "pnl", "realized", data.get("realized_pnl"))
        add(record, "pnl", "unrealized", data.get("unrealized_pnl"))
        add(record, "cash_movement", "pay_in_today", data.get("funds_added"))
        add(record, "cash_movement", "pay_out_today", data.get("funds_withdrawn"))

        add_segment(record, "equity", available_balance=number(detail.get("eq_cnc")) + number(detail.get("eq_mis"))
                    + number(detail.get("eq_mtf")))
        add_segment(record, "derivatives", available_balance=number(detail.get("future")) + number(detail.get("option_buy"))
                    + number(detail.get("option_sell")))
        add_segment(record, "commodity", available_balance=detail.get("comm_option_buy"))
        return record

    def is_authentication_error(self, exception):
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
