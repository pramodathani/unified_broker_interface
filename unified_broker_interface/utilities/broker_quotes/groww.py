"""
Groww quotes, from `GET https://api.groww.in/v1/live-data/quote?exchange=<EXCHANGE>&segment=<SEGMENT>&trading_symbol=<SYMBOL>`.

**Not yet verified against the live API.** On 2026-09-13 this account's token - valid, with the roles
`order-basic,non_trading-basic,order_read_only-basic` - was refused with HTTP 403 "Access forbidden for
this request." on both `live-data/quote` and `live-data/ltp`, the same refusal the historical endpoint
gives, so the account is not entitled to Groww's live data. The response shape below is Groww's published
example rather than a measurement; check it in a session on an entitled account.

Groww addresses an instrument on this endpoint by exchange, segment and trading symbol. The trading
symbol is Groww's order symbol in unified.broker_mappings. The segment is Groww's own: `CASH` for
equities, funds and indices, `FNO` for NSE and BSE derivatives, `COMMODITY` for MCX. The market feed names
the instrument on ticks as `EXCHANGE|SEGMENT|EXCHANGE_TOKEN` - `NSE|CASH|2885` - with the exchange token
that broker_mappings stores as Groww's broker token, so that is the tick's `instrument_token`. The client
sends `X-API-Version: 1.0` and unwraps the response's `payload`.

How the documented fields become the feed's tick:

- `last_price`, `average_price` and `ohlc` are rupees. The feed's protobuf prices are paise, which the
  feed divides by 100, so the two agree without conversion. Groww's example prints `ohlc` as a string,
  `"{open: 149.5,high: 150.5,low: 148.5,close: 149.5}"`, so both that and an object are read.
- `ohlc.close` is passed through as the feed's `close` is. The Groww normalizer does not take either as
  the previous close, so it does not reach a quote document whatever it turns out to mean.
- `volume`, `total_buy_quantity`, `total_sell_quantity`, `open_interest`, `last_trade_quantity` and each
  book level's `quantity` are whole numbers, as the feed publishes them. The normalizer takes Groww's
  quantities to be units; on NSE and BSE that is what the exchanges report. Groww's feed does not stream
  MCX, so on MCX there is no feed fact to match and whether REST reports lots is unknown.
- Book levels are `{price, quantity}` without order counts, so `orders` is None, as on the feed.
- `last_trade_time` is epoch milliseconds and becomes epoch seconds. The normalizer does not use a Groww
  last trade time. The endpoint carries no exchange feed time, so `exchange_timestamp` is left empty
  rather than filled with the trade time.

A refusal that is not about the session - the 403 an unentitled account gets, or a rate limit - pauses
this module, so the service moves on to the next broker instead of asking Groww again on every uncached
request.
"""

import re

from stock_brokers.api.groww import GrowwAPIException
from unified_broker_interface.utilities.broker_quotes.base import BrokerQuoteSource, QuoteUnavailable, contract_tick
from unified_broker_interface.utilities.broker_quotes.utilities.pause import RefusalPause
from utilities.configurations import get_logger

logger = get_logger("rest_api.quotes.groww")

QUOTE_URL = "https://api.groww.in/v1/live-data/quote"

# How long to send nothing after a refusal for entitlement, and after a rate limit.
FORBIDDEN_PAUSE_SECONDS = 15 * 60
THROTTLE_PAUSE_SECONDS = 60

_OHLC_TEXT = re.compile(r"(open|high|low|close)\s*:\s*(-?\d+(?:\.\d+)?)")

_AUTHENTICATION_MARKERS = ("unauthori", "authentication", "token expired", "invalid token", "expired token",
                           "jwt")

def _status(exception):
    """
    The HTTP status or Groww code a refusal carries, as text.
    """
    return str(getattr(exception, "code", "") or "").strip().upper()

def _is_forbidden(exception):
    """
    Whether a refusal is Groww's 403 for an account without the entitlement.
    """
    return _status(exception) == "403" or "access forbidden" in str(exception).lower()

def _is_throttle(exception):
    """
    Whether a refusal is a rate limit.
    """
    lowered = str(exception).lower()
    return _status(exception) == "429" or "too many requests" in lowered or "rate limit" in lowered

def _segment(identity):
    """
    Groww's segment for an instrument: COMMODITY on MCX, FNO for other derivatives, CASH otherwise.
    """
    if identity["exchange"] == "mcx":
        return "COMMODITY"
    if identity.get("shape") in ("future", "option"):
        return "FNO"
    return "CASH"

def _ohlc(value):
    """
    Groww's `ohlc`, an object or the text `{open: 1,high: 2,low: 3,close: 4}`, as a dict of floats.
    """
    if isinstance(value, dict):
        return {key: value.get(key) for key in ("open", "high", "low", "close")}
    found = dict(_OHLC_TEXT.findall(str(value or "")))
    return {key: float(found[key]) if key in found else None for key in ("open", "high", "low", "close")}

def _whole(value):
    """
    A quantity as a whole number, as the feed publishes it, or None.
    """
    try:
        return int(round(float(value))) if value is not None else None
    except (TypeError, ValueError):
        return None

def _levels(levels):
    """
    Groww `{price, quantity}` book levels as the feed's `{price, quantity, orders}`.
    """
    return [{"price": level.get("price"), "quantity": _whole(level.get("quantity")), "orders": None}
            for level in (levels or [])[:5]]

class GrowwQuoteSource(BrokerQuoteSource):
    """
    Fetches Groww quotes.
    """

    BROKER_NAME = "groww"

    def __init__(self):
        self._pause = RefusalPause()

    def fetch(self, client, handle, identity, received_at):
        token = str(handle.get("broker_token") or "").strip()
        trading_symbol = str(handle.get("order_symbol") or "").strip()
        if not token or not trading_symbol:
            raise QuoteUnavailable(f"Groww has no trading symbol for broker token {token or None}")
        paused = self._pause.remaining()
        if paused is not None:
            raise QuoteUnavailable(f"Groww quotes are paused for {paused[0]:.0f}s more: {paused[1]}")

        exchange, segment = identity["exchange"].upper(), _segment(identity)
        try:
            response = client.get(url=QUOTE_URL, timeout=self.TIMEOUT_SECONDS,
                                  params={"exchange": exchange, "segment": segment, "trading_symbol": trading_symbol})
        except GrowwAPIException as exception:
            if _is_forbidden(exception):
                self._pause.pause(FORBIDDEN_PAUSE_SECONDS, f"refused as forbidden, so not entitled to live data: {exception.message}")
                logger.warning(f"Groww refused live data as forbidden; pausing quotes: {exception.message}")
            elif _is_throttle(exception):
                self._pause.pause(THROTTLE_PAUSE_SECONDS, f"rate limited: {str(exception)[:120]}")
                logger.warning(f"Groww rate limited quote requests; pausing: {str(exception)[:160]}")
            raise

        # The client returns None for an error body without a code and message, rather than raising.
        quote = (response or {}).get("data")
        if not isinstance(quote, dict) or quote.get("last_price") is None:
            raise QuoteUnavailable(f"Groww returned no quote for {exchange} {segment} {trading_symbol}: {str(quote)[:200]}")

        tick = contract_tick(self.BROKER_NAME, f"{exchange}|{segment}|{token}", identity["exchange"], received_at)
        ohlc = _ohlc(quote.get("ohlc"))
        last_price, close = quote.get("last_price"), ohlc["close"]
        tick["last_price"] = last_price
        tick["last_quantity"] = _whole(quote.get("last_trade_quantity"))
        tick["average_price"] = quote.get("average_price")
        tick["volume"] = _whole(quote.get("volume"))
        tick["buy_quantity"] = _whole(quote.get("total_buy_quantity"))
        tick["sell_quantity"] = _whole(quote.get("total_sell_quantity"))
        tick["ohlc"] = ohlc
        tick["change"] = (last_price - close) * 100 / close if last_price is not None and close else None
        tick["oi"] = _whole(quote.get("open_interest"))
        last_trade_time = quote.get("last_trade_time")
        tick["last_trade_time"] = last_trade_time / 1000 if isinstance(last_trade_time, (int, float)) and last_trade_time else None
        depth = quote.get("depth") or {}
        tick["depth"] = {"buy": _levels(depth.get("buy")), "sell": _levels(depth.get("sell"))}
        tick["mode"] = "full" if tick["depth"]["buy"] or tick["depth"]["sell"] else "quote"
        return tick

    def is_authentication_error(self, exception):
        if _is_forbidden(exception) or _is_throttle(exception):
            return False
        if _status(exception) == "401":
            return True
        lowered = str(exception).lower()
        return any(marker in lowered for marker in _AUTHENTICATION_MARKERS)
