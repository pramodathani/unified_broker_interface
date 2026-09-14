"""
Stoxkart funds, from `GET https://openapi.stoxkart.com/funds`.

The API client unwraps Stoxkart's `data` and sends the four headers Stoxkart requires together - client
id, platform, API key and access token. Stoxkart reports one pool with no segment breakdown, so nothing
goes into the segments. The available balance is stated, as `net`; beside it are the cash, the pledge
value, the adhoc limit, the withdrawable funds, the realised profit and the day's pay-in and payout. The
amount used, `utilized_limit`, is sent as a negative number and is read as its size, as every other broker
reports it.

A dead session is refused with the code `AuthorizationError` - "Session is not present", measured on
2026-09-13. Stoxkart's login is a known issue that is left alone: no service keeps its session alive, and
a request must not try to log it in. So a refused session is reported as Stoxkart failing, never taken for
a session problem the service would log in to fix.
"""

from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  funds_record, number)

FUNDS_URL = "https://openapi.stoxkart.com/funds"

class StoxkartFundsSource(BrokerFundsSource):
    """
    Reads Stoxkart funds.
    """

    BROKER_NAME = "stoxkart"

    def fetch(self, client):
        data = (client.get(url=FUNDS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if not isinstance(data, dict):
            raise FundsUnavailable(f"Stoxkart answered the funds request without funds: {str(data)[:200]}")
        return data

    def normalize(self, data):
        record = funds_record()
        add(record, "summary", "available_balance", data.get("net"))
        add(record, "summary", "cash_balance", data.get("cash"))
        add(record, "summary", "collateral_value", data.get("pledge_value"))
        add(record, "summary", "adhoc_credit", data.get("adhoc_limit"))
        add(record, "summary", "margin_utilized", abs(number(data.get("utilized_limit"))))
        add(record, "summary", "withdrawable_balance", data.get("withdrawable_funds"))
        add(record, "pnl", "realized", data.get("realised_profit"))
        add(record, "cash_movement", "pay_in_today", data.get("payin_amount"))
        add(record, "cash_movement", "pay_out_today", data.get("payout_amount"))
        return record

    def is_authentication_error(self, exception):
        # Stoxkart is never logged in from here; see the module docstring.
        return False
