"""
Zerodha (Kite) quotes, from `GET https://api.kite.trade/quote`.

Kite addresses an instrument on this endpoint by `EXCHANGE:TRADINGSYMBOL` or by its instrument token;
the token is used, because it is what unified.broker_mappings stores and what Zerodha's ticks carry.
The response is keyed by the same value.

Kite's quote carries the same fields its market feed's full mode does, under the same names, so the
tick is a near copy. Two differences: `last_trade_time` and `timestamp` are India time strings rather
than epochs, and `timestamp` is the feed's `exchange_timestamp`. The quantities are in lots on MCX and
`ohlc.close` is the previous session's close, exactly as on the feed, which the Zerodha tick normalizer
already accounts for.
"""

from datetime import datetime

from unified_broker_interface.utilities.broker_quotes.base import BrokerQuoteSource, QuoteUnavailable, contract_tick
from unified_broker_interface.utilities.instrument_identity import INDIA

QUOTE_URL = "https://api.kite.trade/quote"

_AUTHENTICATION_MARKERS = ("tokenexception", "access_token", "invalid api", "incorrect `api_key`")

def _epoch(value):
    """
    A Kite `YYYY-MM-DD HH:MM:SS` India time string as epoch seconds.

    - `value` is the string, or None.
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=INDIA).timestamp()
    except ValueError:
        return None

class ZerodhaQuoteSource(BrokerQuoteSource):
    """
    Fetches Zerodha quotes.
    """

    BROKER_NAME = "zerodha"

    def fetch(self, client, handle, identity, received_at):
        token = str(handle["broker_token"])
        response = client.get(url=QUOTE_URL, params={"i": token}, timeout=self.TIMEOUT_SECONDS)
        quote = (response.get("data") or {}).get(token)
        if not quote:
            raise QuoteUnavailable(f"Kite returned no quote for instrument token {token}")

        tick = contract_tick(self.BROKER_NAME, int(token), identity["exchange"], received_at)
        for field in ("last_price", "last_quantity", "average_price", "volume", "buy_quantity", "sell_quantity",
                      "oi", "oi_day_high", "oi_day_low"):
            tick[field] = quote.get(field)
        tick["ohlc"] = {key: (quote.get("ohlc") or {}).get(key) for key in ("open", "high", "low", "close")}
        depth = quote.get("depth") or {}
        tick["depth"] = {side: list(depth.get(side) or []) for side in ("buy", "sell")}
        tick["last_trade_time"] = _epoch(quote.get("last_trade_time"))
        tick["exchange_timestamp"] = _epoch(quote.get("timestamp"))
        return tick

    def is_authentication_error(self, exception):
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
