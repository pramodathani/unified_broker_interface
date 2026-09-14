"""
Fyers quotes, from `GET https://api-t1.fyers.in/data/depth?symbol=<symbol>&ohlcv_flag=1`.

**Not yet verified against the live API.** The first request on 2026-09-13 was refused with HTTP 429
"request limit reached" while the Fyers candle downloader was running, and no further request was sent,
so the response shape below is Fyers' published v3 example rather than a measurement. Check every
statement marked *documented* in a live session before this broker is relied on.

Fyers addresses an instrument by its symbol - `NSE:RELIANCE-EQ`, `MCX:CRUDEOIL26SEPFUT` - which
unified.broker_mappings stores as Fyers' order symbol, and its market feed names the instrument on
every tick by that same symbol, so the symbol is both the request parameter and the tick's
`instrument_token`. The authorization header is the application id and access token joined by a colon,
which `FyersAPI` already sends. The body is `{"s": "ok", "d": {<symbol>: {...}}}`; `FyersAPI` unwraps only
a `data` key, so `d` is read here.

The depth endpoint is used rather than `/data/quotes` because one call carries everything the feed's full
tick does - five levels of the book with order counts, open, high, low, the previous close, last price,
last quantity and time, volume, average price, open interest and the total bid and offer quantities -
where `/data/quotes` has no book and no open interest.

How the documented fields become the feed's tick:

- `ltp`, `o`, `h`, `l`, `atp` are rupees, as the feed's are once it divides out its scale.
- `c` is the previous session's close, which is what the feed's `prev_close_price` is and what the
  normalizer's CLOSE_ALWAYS takes it to be. In Fyers' documented example `ch` equals `ltp - c`; when a
  response disagrees by more than a paisa, `ltp - ch` is used, because `ch` is Fyers' change against the
  previous close in both its REST and feed vocabularies.
- `ltq`, `v`, `totalbuyqty`, `totalsellqty`, `oi` and each level's `volume` are passed through unscaled.
  The normalizer takes every MCX quantity from Fyers to be lots, as the feed's are; that REST reports
  them in the same unit is *documented* only by Fyers giving MCX contracts a lot size of 1.
- `bids` and `ask` levels of `{price, volume, ord}` become `{price, quantity, orders}`.
- `ltt` is epoch seconds and is the last trade time. The endpoint carries no exchange feed time, so
  `exchange_timestamp` is left empty rather than filled with the trade time.

Currency derivatives are refused before any request: the Fyers normalizer excludes them, so a quote
could never be resolved and the call would only spend the rate limit.

Fyers sits behind Cloudflare, which bans an IP address that sends too much, and every further request
extends the ban. A block page or a rate limit refusal therefore pauses this module - it sends nothing
until the pause ends and the service moves on to the next broker - rather than letting every uncached
quote request knock on the door again.
"""

from stock_brokers.api.fyers import FyersAPIException
from stock_brokers.instruments.historical.fyers import AUTHENTICATION_ERROR_CODES, BLOCK_PAGE_MARKERS
from unified_broker_interface.utilities.broker_quotes.base import BrokerQuoteSource, QuoteUnavailable, contract_tick
from unified_broker_interface.utilities.broker_quotes.utilities.pause import RefusalPause
from utilities.configurations import get_logger

logger = get_logger("rest_api.quotes.fyers")

DEPTH_URL = "https://api-t1.fyers.in/data/depth"

# Fyers' code for a symbol it does not know.
UNKNOWN_SYMBOL_CODE = -300

# How long to send nothing after Cloudflare's block page, and after Fyers' own rate limit refusal.
BLOCK_PAUSE_SECONDS = 30 * 60
THROTTLE_PAUSE_SECONDS = 5 * 60

# A disagreement between `c` and `ltp - ch` larger than this is taken to mean `c` is not the previous close.
CLOSE_TOLERANCE = 0.01

def _code(exception):
    """
    The numeric code a Fyers refusal carries, or None.
    """
    try:
        return int(getattr(exception, "code", None))
    except (TypeError, ValueError):
        return None

def _is_block(exception):
    """
    Whether a refusal is Cloudflare's IP ban rather than anything Fyers itself said.
    """
    lowered = str(exception).lower()
    return (any(marker in lowered for marker in BLOCK_PAGE_MARKERS)
            or (_code(exception) == 429 and "cloudflare" in lowered))

def _is_throttle(exception):
    """
    Whether a refusal is a rate limit.
    """
    lowered = str(exception).lower()
    return (_code(exception) == 429 or "too many requests" in lowered or "rate limit" in lowered
            or "request limit" in lowered)

def _previous_close(quote):
    """
    The previous session's close from a depth quote, preferring `c` and checking it against `ltp - ch`.
    """
    close, last_price, change = quote.get("c"), quote.get("ltp"), quote.get("ch")
    if last_price and change is not None:
        implied = last_price - change
        if not close or abs(implied - close) > CLOSE_TOLERANCE:
            return round(implied, 4)
    return close or None

def _levels(levels):
    """
    Fyers `{price, volume, ord}` book levels as the feed's `{price, quantity, orders}`.
    """
    return [{"price": level.get("price"), "quantity": level.get("volume"), "orders": level.get("ord")}
            for level in (levels or [])[:5]]

class FyersQuoteSource(BrokerQuoteSource):
    """
    Fetches Fyers quotes.
    """

    BROKER_NAME = "fyers"

    def __init__(self):
        self._pause = RefusalPause()

    def fetch(self, client, handle, identity, received_at):
        symbol = str(handle.get("order_symbol") or "").strip()
        if ":" not in symbol:
            raise QuoteUnavailable(f"Fyers has no symbol for broker token {handle.get('broker_token')}")
        if "_currenc" in str(identity.get("segment") or ""):
            raise QuoteUnavailable("Fyers currency derivative quotes are not normalized; see the Fyers tick normalizer")
        paused = self._pause.remaining()
        if paused is not None:
            raise QuoteUnavailable(f"Fyers quotes are paused for {paused[0]:.0f}s more: {paused[1]}")

        try:
            response = client.get(url=DEPTH_URL, params={"symbol": symbol, "ohlcv_flag": "1"},
                                  timeout=self.TIMEOUT_SECONDS)
        except FyersAPIException as exception:
            if _is_block(exception):
                self._pause.pause(BLOCK_PAUSE_SECONDS, f"Cloudflare blocked this address: {str(exception)[:120]}")
                logger.error(f"Cloudflare is blocking Fyers requests from this address; pausing quotes: {str(exception)[:160]}")
            elif _is_throttle(exception):
                self._pause.pause(THROTTLE_PAUSE_SECONDS, f"rate limited: {str(exception)[:120]}")
                logger.warning(f"Fyers rate limited quote requests; pausing: {str(exception)[:160]}")
            elif _code(exception) == UNKNOWN_SYMBOL_CODE:
                raise QuoteUnavailable(f"Fyers does not know {symbol}: {str(exception)[:160]}") from exception
            raise

        body = (response or {}).get("data") or {}
        if not isinstance(body, dict):
            raise QuoteUnavailable(f"Fyers answered the depth request for {symbol} with {str(body)[:200]}")
        if body.get("s") not in (None, "ok"):
            # Fyers can refuse inside a 200; raised as the API client would, so the session codes are seen.
            exception = FyersAPIException(code=body.get("code"), message=body.get("message"))
            if _code(exception) == UNKNOWN_SYMBOL_CODE:
                raise QuoteUnavailable(f"Fyers does not know {symbol}: {body.get('message')}")
            raise exception
        quote = (body.get("d") or {}).get(symbol)
        if not quote:
            raise QuoteUnavailable(f"Fyers returned no quote for {symbol}")

        tick = contract_tick(self.BROKER_NAME, symbol, identity["exchange"], received_at)
        last_price, close = quote.get("ltp"), _previous_close(quote)
        tick["last_price"] = last_price
        tick["last_quantity"] = quote.get("ltq")
        tick["average_price"] = quote.get("atp")
        tick["volume"] = quote.get("v")
        tick["buy_quantity"] = quote.get("totalbuyqty")
        tick["sell_quantity"] = quote.get("totalsellqty")
        tick["ohlc"] = {"open": quote.get("o"), "high": quote.get("h"), "low": quote.get("l"), "close": close}
        tick["change"] = (last_price - close) * 100 / close if last_price is not None and close else None
        tick["oi"] = quote.get("oi")
        tick["last_trade_time"] = quote.get("ltt") or None
        tick["depth"] = {"buy": _levels(quote.get("bids")), "sell": _levels(quote.get("ask"))}
        tick["mode"] = "full" if tick["depth"]["buy"] or tick["depth"]["sell"] else "quote"
        return tick

    def is_authentication_error(self, exception):
        if _is_block(exception) or _is_throttle(exception):
            return False
        if _code(exception) in AUTHENTICATION_ERROR_CODES:
            return True
        lowered = str(exception).lower()
        return ("could not authenticate" in lowered or "token expired" in lowered
                or ("token" in lowered and "invalid" in lowered) or "unauthor" in lowered)
