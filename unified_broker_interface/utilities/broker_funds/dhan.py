"""
Dhan funds, from `GET https://api.dhan.co/v2/fundlimit`.

Dhan reports one pool with no segment breakdown, so nothing goes into the segments. The available balance
is stated, under Dhan's own spelling `availabelBalance`; beside it are the collateral, the amount used, the
withdrawable balance, the amount receivable, which is not yet usable, and the payout blocked for a
withdrawal.

A dead session is refused with `errorType` `Invalid_Authentication` and code DH-901, which the API client
raises as the exception's `code` and message.
"""

from unified_broker_interface.utilities.broker_funds.base import BrokerFundsSource, FundsUnavailable, add, funds_record

FUND_LIMIT_URL = "https://api.dhan.co/v2/fundlimit"

class DhanFundsSource(BrokerFundsSource):
    """
    Reads Dhan funds.
    """

    BROKER_NAME = "dhan"

    def fetch(self, client):
        data = (client.get(url=FUND_LIMIT_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if not isinstance(data, dict):
            raise FundsUnavailable(f"Dhan answered the fund limit request without funds: {str(data)[:200]}")
        return data

    def normalize(self, data):
        record = funds_record()
        add(record, "summary", "available_balance", data.get("availabelBalance"))
        add(record, "summary", "collateral_value", data.get("collateralAmount"))
        add(record, "summary", "margin_utilized", data.get("utilizedAmount"))
        add(record, "summary", "withdrawable_balance", data.get("withdrawableBalance"))
        add(record, "cash_movement", "uncleared_funds", data.get("receiveableAmount"))
        add(record, "cash_movement", "pending_withdrawal", data.get("blockedPayoutAmount"))
        return record

    def is_authentication_error(self, exception):
        code = str(getattr(exception, "code", "") or "").lower()
        return code == "invalid_authentication" or "dh-901" in str(exception).lower()
