"""
Dhan quotes, from `POST https://api.dhan.co/v2/marketfeed/quote`.

The body names instruments by Dhan exchange segment and security id - `{"NSE_EQ": [2885]}` - and the
answer is keyed the same way, under `data.data`. The segment is derived from the instrument's canonical
exchange and segment, because a security id is reused across segments. The request needs the
`client-id` header as well as `access-token`, which the API client's default headers lack, so both are
passed. NSE commodity options have no Dhan segment name and cannot be quoted.

The quote carries the market feed's full packet under the feed's own names, so the tick is a near copy,
with `instrument_token` spelled as the feed spells it, the segment by number: `5:565899`. Measured on
2026-09-13 against the stored feed and Zerodha:

- Prices are rupees, and MCX quantities are lots (CRUDEOIL volume 70691, open interest 17552), as on the
  feed.
- `ohlc.close` means what the feed packet's close field means: the previous close while the session
  runs and the day's own close after it (RELIANCE read 1257.5, its last price, on the Sunday after).
  Dhan's normalizer only uses it before the session's close.
- `last_trade_time` is a `DD/MM/YYYY HH:MM:SS` India time string rather than an epoch. There is no
  exchange timestamp, which the feed does not send either.
- An empty order book comes back as five zero rows, as on the feed.
"""

from datetime import datetime

from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, INDEX_SEGMENTS,
                                                                  split_segment_value)
from stock_brokers.instruments.ticks.dhan import DhanTickNormalizer
from unified_broker_interface.utilities.broker_quotes.base import BrokerQuoteSource, QuoteUnavailable, contract_tick
from unified_broker_interface.utilities.instrument_identity import INDIA

QUOTE_URL = "https://api.dhan.co/v2/marketfeed/quote"

# Invalid_Authentication is the error type of a refused token; the data APIs answer a dead or foreign
# token with HTTP 401 and `{"data": {"808": "Authentication Failed - Client ID or Token invalid"}}`, and
# an expired one with 807. 806, data APIs not subscribed, is deliberately absent: logging in cannot fix it.
_AUTHENTICATION_MARKERS = ("invalid_authentication", "authentication failed", "token invalid", "token is expired",
                           '"807"', '"808"')

def dhan_segment(identity):
    """
    Dhan's exchange segment name for an instrument, or None when Dhan has none.

    - `identity` is the instrument's identity.
    """
    exchange, bare = split_segment_value(identity["segment"])
    if bare in INDEX_SEGMENTS:
        return "IDX_I"
    if exchange == "mcx":
        return "MCX_COMM"
    if exchange not in ("nse", "bse"):
        return None
    if bare in CASH_SEGMENTS:
        return f"{exchange.upper()}_EQ"
    if bare.startswith("currency_"):
        return f"{exchange.upper()}_CURRENCY"
    if bare.startswith("commodity_"):
        return None
    return f"{exchange.upper()}_FNO"

def _epoch(value):
    """
    A Dhan `DD/MM/YYYY HH:MM:SS` India time string as epoch seconds.

    - `value` is the string, or None.
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%d/%m/%Y %H:%M:%S").replace(tzinfo=INDIA).timestamp()
    except ValueError:
        return None

class DhanQuoteSource(BrokerQuoteSource):
    """
    Fetches Dhan quotes.
    """

    BROKER_NAME = "dhan"

    def fetch(self, client, handle, identity, received_at):
        segment = dhan_segment(identity)
        if segment is None:
            raise QuoteUnavailable(f"Dhan has no quote segment for {identity['segment']}")
        security_id = str(handle["broker_token"])
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": client._current_login()["access_token"],
            "client-id": str(client._settings["client_id"]),
        }
        response = client.post(url=QUOTE_URL, json={segment: [int(security_id)]}, headers=headers,
                               timeout=self.TIMEOUT_SECONDS)
        quote = ((((response.get("data") or {}).get("data") or {}).get(segment)) or {}).get(security_id)
        if not quote:
            raise QuoteUnavailable(f"Dhan returned no quote for {segment} {security_id}")

        token = f"{DhanTickNormalizer.SEGMENT_NAMES[segment]}:{security_id}"
        tick = contract_tick(self.BROKER_NAME, token, identity["exchange"], received_at)
        for field in ("last_price", "last_quantity", "average_price", "volume", "buy_quantity", "sell_quantity",
                      "oi", "oi_day_high", "oi_day_low"):
            tick[field] = quote.get(field)
        ohlc = quote.get("ohlc") or {}
        tick["ohlc"] = {key: ohlc.get(key) for key in ("open", "high", "low", "close")}
        close, last_price = tick["ohlc"]["close"], tick["last_price"]
        tick["change"] = (last_price - close) * 100 / close if close and last_price is not None else None
        depth = quote.get("depth") or {}
        tick["depth"] = {side: [{"quantity": level.get("quantity"), "price": level.get("price"),
                                 "orders": level.get("orders")} for level in depth.get(side) or []]
                         for side in ("buy", "sell")}
        tick["last_trade_time"] = _epoch(quote.get("last_trade_time"))
        return tick

    def is_authentication_error(self, exception):
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
