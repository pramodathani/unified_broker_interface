"""
Kotak Neo quotes, from `GET {base_url}/script-details/1.0/quotes/neosymbol/{segment}|{token}/all`.

`base_url` is the host Kotak assigned the session at login, which the API client reads from the stored
login. The endpoint authenticates with the consumer key alone, sent as `Authorization`: measured on
2026-09-13, the key by itself answers, the session's `Auth` and `Sid` by themselves are refused with 401
"unauthorised", and a wrong key with 424 "Consumer key ... is invalid". The session headers are sent
alongside the key anyway - Kotak accepts the combination - so a later change to require them is met by
the service's one login rather than by a refusal nothing can fix. The request is made here rather than
through the API client because the client drops `timeout`.

**Addressing.** An instrument is `segment|token` in Kotak's segment vocabulary. The bare token is reused
across segments, so the segment is derived from the instrument's canonical exchange and segment. That
derivation was checked against every Kotak mapping of 2026-09-13 joined back to `kotak.instruments` on
token and trading symbol: NSE currencies go to `cde_fo`, NSE commodities to `nse_com`, other NSE
derivatives to `nse_fo`, other NSE instruments to `nse_cm`, BSE derivatives to `bse_fo`, BSE cash to
`bse_cm`, and everything on MCX to `mcx_fo`. The one ambiguity is `nse_uncategorised`, where 7 of 24 rows
sit in `cde_fo`; those are asked for under `nse_cm` and come back as unavailable. NSE indices are the
exception to token addressing: Kotak answers `nse_cm|26000` with 400 "Invalid neosymbol values" and wants
the index's name, `nse_cm|Nifty 50`, so the four NSE indices Kotak lists are named in `INDEX_NAMES`. MCX
indices are addressed by token (`mcx_fo|567` answers).

**The tick.** Its `instrument_token` is `segment|token`, as the market feed spells it - for indices too,
with the token rather than the name, because the token is what unified.broker_mappings stores.
Compared with the stored feed ticks and with Zerodha on the same instruments, on 2026-09-13 after
Friday's close:

- Values arrive as strings, prices in rupees - the feed's per segment price divider is already applied.
- `ohlc.close` is not the previous close, which the feed's close is: RELIANCE's REST close read 1257.5,
  its last price, where the feed read 1274.0, and CRUDEOIL SEP 9527 against the feed's 9722. `change` is
  the last price less the previous close (-16.5 and -195), so `ohlc.close` is rebuilt as
  `ltp - change`, which reproduces the feed's figure on both.
- MCX quantities have the feed's bases: open interest in lots (CRUDEOIL SEP 17552, GOLD OCT 9618, the
  feed's figures) and last quantity in lots times Kotak's own lot size (CRUDEOIL 100, GOLD 3). The other
  quantities are passed as they come, which a live session has to confirm against the feed.
- `last_volume` is the volume, `total_buy` and `total_sell` the pending quantities, `avg_cost` the
  average price and `open_int` the open interest.
- `lstup_time` is a date, not a time, and not the feed's date either: RELIANCE read
  `Fri Sep 11 2026 05:30:00 GMT+0530` where the feed's last update read 00:00 India time that day, and
  instruments without one read a 1900 placeholder. Kotak's normalizer does not trust the feed's times,
  so both time fields are left empty rather than filled with a figure known to disagree with the feed.
- An index quote carries zeros for every quantity; the feed's index packet carries none, so they are
  left empty.
- An empty order book is five zero rows, which the normalizer drops.
"""

import requests

from stock_brokers.api.kotak import KotakAPIException
from stock_brokers.instruments.mapping.utilities.segments import INDEX_SEGMENTS, split_segment_value
from unified_broker_interface.utilities.broker_quotes.base import BrokerQuoteSource, QuoteUnavailable, contract_tick

QUOTE_PATH = "/script-details/1.0/quotes/neosymbol/{neosymbol}/all"

# The names Kotak's quote endpoint takes for the NSE indices it lists, by the token the mapping stores.
INDEX_NAMES = {
    "26000": "Nifty 50",
    "26009": "Nifty Bank",
    "26037": "Nifty Fin Service",
    "26074": "NIFTY MID SELECT",
}

# A refusal logging in can remedy: Kotak's 401 for a session it does not accept, and stCode 200032 for a
# request sent to a host other than the one the current login was assigned. A 424 for an invalid consumer
# key is deliberately absent - the key comes from the settings, and no login changes it.
_AUTHENTICATION_MARKERS = ("unauthorised", "unauthorized", "200032", "invalid url", "baseurl")

def kotak_segment(identity):
    """
    Kotak's exchange segment for an instrument, or None when Kotak has none.

    - `identity` is the instrument's identity.
    """
    exchange, bare = split_segment_value(identity["segment"])
    derivative = identity.get("shape") in ("future", "option")
    if exchange == "mcx":
        return "mcx_fo"
    if exchange == "nse":
        if bare.startswith("currenc"):
            return "cde_fo"
        if bare.startswith("commodit"):
            return "nse_com"
        return "nse_fo" if derivative else "nse_cm"
    if exchange == "bse":
        if not derivative:
            return "bse_cm"
        if bare.startswith("currenc"):
            return "bse_cd"
        if bare.startswith("commodit"):
            return "bse_co"
        return "bse_fo"
    return None

def _price(value):
    """
    A Kotak string price as a float, or None.

    - `value` is the string.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _quantity(value):
    """
    A Kotak string quantity as an integer, or None.

    - `value` is the string.
    """
    number = _price(value)
    return None if number is None else int(round(number))

class KotakQuoteSource(BrokerQuoteSource):
    """
    Fetches Kotak Neo quotes.
    """

    BROKER_NAME = "kotak"

    def fetch(self, client, handle, identity, received_at):
        token = str(handle["broker_token"])
        segment = kotak_segment(identity)
        if segment is None:
            raise QuoteUnavailable(f"Kotak has no exchange segment for {identity['segment']}")
        index = split_segment_value(identity["segment"])[1] in INDEX_SEGMENTS
        name = token
        if index and segment == "nse_cm":
            name = INDEX_NAMES.get(token)
            if name is None:
                raise QuoteUnavailable(f"Kotak's quote name for index token {token} is not known")

        login = client._current_login() or {}
        headers = {"Authorization": str(client._settings["api_key"]), "neo-fin-key": "neotradeapi",
                   "Auth": str(login.get("access_token")), "Sid": str(login.get("sid"))}
        response = requests.get(client.url(QUOTE_PATH.format(neosymbol=f"{segment}|{name}")), headers=headers,
                                timeout=self.TIMEOUT_SECONDS)
        if response.status_code == 400 and "neosymbol" in response.text.lower():
            raise QuoteUnavailable(f"Kotak does not recognise {segment}|{name}")
        if response.status_code >= 300:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        try:
            payload = response.json()
        except ValueError:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        quotes = payload if isinstance(payload, list) else (payload or {}).get("data")
        quote = next((item for item in quotes or [] if isinstance(item, dict)
                      and str(item.get("exchange_token")) == name), None)
        if quote is None:
            raise QuoteUnavailable(f"Kotak returned no quote for {segment}|{name}")

        tick = contract_tick(self.BROKER_NAME, f"{segment}|{token}", identity["exchange"], received_at)
        last_price = _price(quote.get("ltp"))
        change = _price(quote.get("change"))
        ohlc = quote.get("ohlc") or {}
        tick["last_price"] = last_price
        tick["ohlc"] = {"open": _price(ohlc.get("open")), "high": _price(ohlc.get("high")),
                        "low": _price(ohlc.get("low")),
                        "close": last_price - change if last_price is not None and change is not None else None}
        if index:
            return tick

        tick["last_quantity"] = _quantity(quote.get("last_traded_quantity"))
        tick["average_price"] = _price(quote.get("avg_cost"))
        tick["volume"] = _quantity(quote.get("last_volume"))
        tick["buy_quantity"] = _quantity(quote.get("total_buy"))
        tick["sell_quantity"] = _quantity(quote.get("total_sell"))
        tick["oi"] = _quantity(quote.get("open_int"))
        depth = quote.get("depth") or {}
        tick["depth"] = {side: [{"quantity": _quantity(row.get("quantity")), "price": _price(row.get("price")),
                                 "orders": _quantity(row.get("orders"))}
                                for row in depth.get(side) or [] if isinstance(row, dict)]
                         for side in ("buy", "sell")}
        return tick

    def is_authentication_error(self, exception):
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
