"""
Fyers funds, from `GET https://api-t1.fyers.in/api/v3/funds`.

Fyers answers with `fund_limit`, a list of titled rows - "Available Balance", "Clear Balance",
"Collaterals", "Adhoc Limit", "Utilized Amount", "Realized Profit and Loss" and others - each carrying an
`equityAmount` and a `commodityAmount`. So the titles are the fields and the two amounts are the segments:
the account's figure is the sum of the two, and the available and utilized rows become the equity and
commodity segments. The body has no `data` envelope, so the API client passes it through whole.

**Refusals.** A dead session is Fyers code -8, -15, -16 or -17, which Fyers can send inside an HTTP 200 as
well as with an error status. Cloudflare in front of the host bans an address that keeps sending refused
requests, and that ban is not a session problem - logging in would be one more refused request and extend
it - so a ban pauses Fyers account calls for thirty minutes and a rate limit for five, and while paused Fyers
is reported as failed without being asked. The pause and these checks are shared with the holdings module.
"""

from stock_brokers.api.fyers import FyersAPIException
from stock_brokers.instruments.historical.fyers import AUTHENTICATION_ERROR_CODES, BLOCK_PAGE_MARKERS
from unified_broker_interface.utilities.broker_funds.base import (BrokerFundsSource, FundsUnavailable, add,
                                                                  add_segment, funds_record, number)
from unified_broker_interface.utilities.broker_quotes.utilities.pause import RefusalPause
from utilities.configurations import get_logger

logger = get_logger("rest_api.funds.fyers")

FUNDS_URL = "https://api-t1.fyers.in/api/v3/funds"

BLOCK_PAUSE_SECONDS = 30 * 60
THROTTLE_PAUSE_SECONDS = 5 * 60

# One pause for every Fyers account call in this process: a ban or a rate limit is on the address and the
# application, not on the endpoint that happened to meet it, so the holdings module holds back on it too.
PAUSE = RefusalPause()

def refusal_code(exception):
    """
    The numeric code a Fyers refusal carries, or None.
    """
    try:
        return int(getattr(exception, "code", None))
    except (TypeError, ValueError):
        return None

def is_block(exception):
    """
    Whether a refusal is Cloudflare's address ban rather than anything Fyers itself said.
    """
    lowered = str(exception).lower()
    return (any(marker in lowered for marker in BLOCK_PAGE_MARKERS)
            or (refusal_code(exception) == 429 and "cloudflare" in lowered))

def is_throttle(exception):
    """
    Whether a refusal is a rate limit.
    """
    lowered = str(exception).lower()
    return (refusal_code(exception) == 429 or "too many requests" in lowered or "rate limit" in lowered
            or "request limit" in lowered)

def is_authentication_error(exception):
    """
    Whether a Fyers refusal means the session is dead: one of its session codes, and not a ban or a limit.
    """
    if is_block(exception) or is_throttle(exception):
        return False
    return refusal_code(exception) in AUTHENTICATION_ERROR_CODES

def paused(what):
    """
    Raise when Fyers account calls are paused.

    - `what` names the call, for the message.

    Raises `RuntimeError` naming the time left and the reason.
    """
    remaining = PAUSE.remaining()
    if remaining is not None:
        raise RuntimeError(f"Fyers {what} are paused for {remaining[0]:.0f}s more: {remaining[1]}")

def note_refusal(exception, what):
    """
    Pause Fyers account calls when a refusal was a ban or a rate limit.

    - `exception` is the refusal.
    - `what` names the call, for the log.
    """
    if is_block(exception):
        PAUSE.pause(BLOCK_PAUSE_SECONDS, f"Cloudflare blocked this address: {str(exception)[:120]}")
        logger.error(f"Cloudflare is blocking Fyers requests from this address; pausing {what}: {str(exception)[:160]}")
    elif is_throttle(exception):
        PAUSE.pause(THROTTLE_PAUSE_SECONDS, f"rate limited: {str(exception)[:120]}")
        logger.warning(f"Fyers rate limited the {what} request; pausing: {str(exception)[:160]}")

class FyersFundsSource(BrokerFundsSource):
    """
    Reads Fyers funds.
    """

    BROKER_NAME = "fyers"

    def fetch(self, client):
        paused("funds")
        try:
            data = (client.get(url=FUNDS_URL, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        except FyersAPIException as exception:
            note_refusal(exception, "funds")
            raise
        if not isinstance(data, dict):
            raise FundsUnavailable(f"Fyers answered the funds request without funds: {str(data)[:200]}")
        if data.get("s") not in (None, "ok"):
            # Fyers can refuse inside a 200; raised as the API client would, so the session codes are seen.
            exception = FyersAPIException(code=data.get("code"), message=data.get("message"))
            note_refusal(exception, "funds")
            raise exception
        return data

    def normalize(self, data):
        record = funds_record()
        rows = {row.get("title"): row for row in data.get("fund_limit") or [] if isinstance(row, dict)}

        def total(title):
            row = rows.get(title) or {}
            return number(row.get("equityAmount")) + number(row.get("commodityAmount"))

        add(record, "summary", "available_balance", total("Available Balance"))
        add(record, "summary", "cash_balance", total("Clear Balance"))
        add(record, "summary", "collateral_value", total("Collaterals"))
        add(record, "summary", "adhoc_credit", total("Adhoc Limit"))
        add(record, "summary", "margin_utilized", total("Utilized Amount"))
        add(record, "pnl", "realized", total("Realized Profit and Loss"))

        available = rows.get("Available Balance")
        utilized = rows.get("Utilized Amount") or {}
        if available:
            add_segment(record, "equity", available_balance=available.get("equityAmount"),
                        margin_utilized=utilized.get("equityAmount"))
            add_segment(record, "commodity", available_balance=available.get("commodityAmount"),
                        margin_utilized=utilized.get("commodityAmount"))
        return record

    def is_authentication_error(self, exception):
        return is_authentication_error(exception)
