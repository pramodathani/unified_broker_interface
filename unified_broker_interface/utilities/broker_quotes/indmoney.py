"""
INDmoney (INDstocks) quotes, from `GET https://api.indstocks.com/market/quotes/full`.

An instrument is named by a scrip code, `NSE_2885`: `NSE` and `BSE` for cash and for indices
(`NSE_40000001`), `NFO` and `BFO` for derivatives. The answer is keyed by the same code, and an unknown
code is refused with "Invalid scrip codes". MCX is not served.

BSE cash is not quoted. For a stock listed on both exchanges INDstocks answers `BSE_500325` with the NSE
listing's quote under the BSE code - last price, volume, order book and even NSE's circuit limits
(1383.2 where BSE's are 1383.8) - and asked for `BSE_500325,NSE_2885` together it returns only the NSE
key. A BSE-only stock (APIS, `BSE_506166`) does get its BSE quote, but nothing in the answer tells the
two apart, so every BSE cash quote is refused rather than an NSE price served as BSE's. BSE indices and
BSE derivatives (`BFO_`) are genuinely BSE's and are quoted.

The market feed spells the same instrument `SEGMENT:TOKEN` with indices on their own segments -
`NSE:2885`, `NFO:47317`, `NIDX:40000001` - and the tick carries that spelling.

The REST quote uses names of its own, mapped onto the feed's contract. Measured on 2026-09-13:

- `live_price`, `day_open`, `day_high`, `day_low`, `volume` and `open_interest` are the last price, the
  day's open, high and low, volume and open interest; prices are rupees and quantities units.
- `prev_close` is the previous session's close even after the bell (RELIANCE 1274.0, as Zerodha), and
  goes in `ohlc.close`, which is where the feed puts it. The INDmoney normalizer does not yet trust
  `close`, so it does not reach the quote until that is settled for the feed.
- The order book is five rows of `{buy, sell}` pairs whose numbers are strings with Indian digit
  grouping - `"1,56,975"`, `"1,257.50"` - and no order counts; `aggregate.total_buy` and `total_sell`
  are the buy and sell quantities.
- There is no last quantity, average price, last trade time or exchange timestamp.
"""

from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, INDEX_SEGMENTS,
                                                                  split_segment_value)
from unified_broker_interface.utilities.broker_quotes.base import BrokerQuoteSource, QuoteUnavailable, contract_tick

QUOTE_URL = "https://api.indstocks.com/market/quotes/full"

# A dead token is refused with HTTP 403 and "The provided access_token is either incorrect, expired, or has
# been revoked. The user needs to re-authenticate."
_AUTHENTICATION_MARKERS = ("access_token", "re-authenticate", "unauthorized")

def indmoney_codes(identity):
    """
    The feed's segment and the REST scrip code prefix for an instrument, or None when INDstocks has no
    quote for it that can be trusted.

    - `identity` is the instrument's identity.
    """
    exchange, bare = split_segment_value(identity["segment"])
    if exchange not in ("nse", "bse"):
        return None
    prefix = exchange.upper()
    if bare in INDEX_SEGMENTS:
        return f"{prefix[0]}IDX", prefix
    if bare in CASH_SEGMENTS:
        # A dual-listed stock's BSE code is answered with its NSE quote; see the module docstring.
        return (prefix, prefix) if exchange == "nse" else None
    if not bare.startswith("equity_"):
        return None
    derivative = f"{prefix[0]}FO"
    return derivative, derivative

def _number(value):
    """
    An INDstocks number, which may be a string with digit grouping, as a float, or None.

    - `value` is the raw value.
    """
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None

def _whole(value):
    """
    An INDstocks quantity as an integer, or None.

    - `value` is the raw value.
    """
    number = _number(value)
    return int(round(number)) if number is not None else None

class IndmoneyQuoteSource(BrokerQuoteSource):
    """
    Fetches INDmoney quotes.
    """

    BROKER_NAME = "indmoney"

    def fetch(self, client, handle, identity, received_at):
        codes = indmoney_codes(identity)
        if codes is None:
            raise QuoteUnavailable(f"INDstocks has no quote segment for {identity['segment']}")
        feed_segment, prefix = codes
        token = str(handle["broker_token"])
        scrip_code = f"{prefix}_{token}"
        try:
            response = client.get(url=QUOTE_URL, params={"scrip-codes": scrip_code}, timeout=self.TIMEOUT_SECONDS)
        except Exception as exception:
            if "invalid scrip" in str(exception).lower():
                raise QuoteUnavailable(f"INDstocks does not know scrip code {scrip_code}") from exception
            raise
        quote = (response.get("data") or {}).get(scrip_code)
        if not quote:
            raise QuoteUnavailable(f"INDstocks returned no quote for {scrip_code}")

        tick = contract_tick(self.BROKER_NAME, f"{feed_segment}:{token}", identity["exchange"], received_at)
        last_price = _number(quote.get("live_price"))
        close = _number(quote.get("prev_close"))
        tick["last_price"] = last_price
        tick["volume"] = _whole(quote.get("volume"))
        tick["oi"] = _whole(quote.get("open_interest"))
        tick["ohlc"] = {"open": _number(quote.get("day_open")), "high": _number(quote.get("day_high")),
                        "low": _number(quote.get("day_low")), "close": close}
        tick["change"] = (last_price - close) * 100 / close if close and last_price is not None else None

        book = ((quote.get("market_depth") or {}).get(scrip_code)) or {}
        aggregate = book.get("aggregate") or {}
        tick["buy_quantity"] = _whole(aggregate.get("total_buy"))
        tick["sell_quantity"] = _whole(aggregate.get("total_sell"))
        for row in book.get("depth") or []:
            for side in ("buy", "sell"):
                level = row.get(side) or {}
                tick["depth"][side].append({"quantity": _whole(level.get("quantity")),
                                            "price": _number(level.get("price")), "orders": None})
        return tick

    def is_authentication_error(self, exception):
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
