"""
Quotes from brokers on the Noren platform, Flattrade and Shoonya, from `GetQuotes`.

**The request.** `GetQuotes` is a POST whose body is `jData={"uid":...,"exch":...,"token":...}&jKey=...`;
the API client adds `uid` and `jKey` and does the wrapping, so only the exchange and the token are named
here. Noren addresses an instrument by its own exchange name and the bare token, and the token is unique
only within that exchange's scrip file, so the exchange matters. It is derived from the identity rather
than read from the broker's raw instruments table: every mapped segment of both brokers sits under exactly
one Noren exchange - cash, funds and indices under `NSE`/`BSE`, currency derivatives under `CDS`/`BCD`,
every other derivative under `NFO`/`BFO`, and `MCX` and `NCX` for the commodity exchanges - which is the
same vocabulary `NorenTickNormalizer.EXCHANGES` reads back. Measured on the 2026-09-12 mappings, the only
exceptions are Shoonya's four `nse_uncategorised` rows filed under `CDS` and Flattrade's two
`uncategorised` rows with no exchange at all; neither resolves through the feed's normalizer anyway.
Shoonya's NCDEX contracts cannot be quoted either: its `NCX` scrip file carries the trading symbol in the
token column (`COTTON20NOV2026`), so that is the stored token, and `GetQuotes` answers it `no data`.

**The response.** A quote answers HTTP 200 with an object whose `stat` is `Ok` and whose fields carry the
same names, and the same units, as the market feed's touchline and depth: every value a string, `lp`, `c`,
`o`, `h`, `l`, `ap`, `v`, `ltq`, `tbq`, `tsq`, `oi` and five levels of `bp`/`bq`/`bo` and `sp`/`sq`/`so`.
So the tick is built from those fields as a streamed Noren tick is. On MCX the quantities are lots, as on
the feed - CRUDEOIL SEP's `oi` 17552 at Shoonya is Zerodha's lots figure and its `tbq` is the sum of its
`bq` levels - so nothing is converted, and the normalizer multiplies by the lot size exactly as it does
for a streamed tick. `c` is the same close the feed carries, the previous session's during a session and
the session's own after it, which the normalizer's close policy handles.

Two fields differ from the feed:

- The feed stamps `ft`, which `GetQuotes` does not carry. It carries `lut`, the last update time as a true
  epoch - Flattrade's RELIANCE `lut` 1789227132 is exactly its `ltd` 12-09-2026 `ltt` 21:02:12 in India
  time - and that is the exchange timestamp.
- The feed gives `ltt` alone, which it dates by `ft`. `GetQuotes` gives the date beside it as `ltd`, so the
  two are read together. An `ltt` of 00:00:00 means the contract has not traded and is read as no time,
  where the feed would turn it into midnight.

A refusal also arrives with HTTP 200, as `{"stat": "Not_Ok", "emsg": ...}`, so the body is inspected and
raised on: a dead session as `NorenRefusal` carrying Noren's message, which `is_authentication_error`
recognises, and anything else as `QuoteUnavailable`. After the exchanges reset a quote may carry no
depth and no open, high or low at all - Shoonya's RELIANCE on a Sunday is `lp` and `c` alone - which is
simply a tick with those fields missing.
"""

from datetime import datetime, timedelta

from unified_broker_interface.utilities.broker_quotes.base import BrokerQuoteSource, QuoteUnavailable, contract_tick
from unified_broker_interface.utilities.instrument_identity import INDIA
from stock_brokers.instruments.mapping.utilities.segments import CASH_SEGMENTS, INDEX_SEGMENTS

# Canonical exchange to its Noren names: (cash and indices, currency derivatives, other derivatives).
_NOREN_EXCHANGES = {
    "nse": ("NSE", "CDS", "NFO"),
    "bse": ("BSE", "BCD", "BFO"),
    "mcx": (None, "MCX", "MCX"),
    "ncdex": (None, "NCX", "NCX"),
}

_CURRENCY_DERIVATIVE_PREFIX = "currency_"

# What Noren says when the session key is no good, lowercased.
_AUTHENTICATION_MARKERS = ("session expired", "invalid session key", "invalid session")

_TRADE_TIME_FORMATS = ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")

# What `ltt` reads for a contract that has not traded in the session: Flattrade's SENSEX 77200 CE on
# 2026-09-12 carried `ltt` 00:00:00 with `ltq` 0 and no high or low. No Indian exchange trades at midnight.
_NO_TRADE_TIME = "00:00:00"

class NorenRefusal(Exception):
    """
    Noren refused a request in the body of an HTTP 200 response.
    """

def noren_exchange(identity):
    """
    The Noren exchange an instrument is quoted under, or None when its segment has none.

    - `identity` is the instrument's identity, with a canonical `exchange` and a prefixed `segment`.
    """
    exchange = identity.get("exchange")
    segment = identity.get("segment") or ""
    names = _NOREN_EXCHANGES.get(exchange)
    if names is None or not segment.startswith(f"{exchange}_"):
        return None
    bare = segment[len(exchange) + 1:]
    if bare in CASH_SEGMENTS or bare in INDEX_SEGMENTS:
        return names[0]
    if bare.startswith(_CURRENCY_DERIVATIVE_PREFIX):
        return names[1]
    return names[2]

def _number(value, cast=float):
    """
    A Noren string field as a number, with blanks and placeholders missing, as the market feed reads it.

    - `value` is the raw field.
    - `cast` is the type wanted.
    """
    if value is None or value == "" or value == "NA":
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None

def _trade_time(time_of_day, trade_date, update_time):
    """
    Noren's last trade time as epoch seconds.

    `GetQuotes` spells the time `HH:MM:SS` and the date beside it `DD-MM-YYYY`, both India time. The other
    spellings the market feed has met are accepted too, and a time with no date is dated by the last update
    time the way the feed dates it by its feed time.

    - `time_of_day` is the `ltt` field.
    - `trade_date` is the `ltd` field, or None.
    - `update_time` is the `lut` epoch, or None.
    """
    if time_of_day is None or time_of_day == "" or time_of_day == "NA":
        return None
    text = str(time_of_day).strip()
    if text == _NO_TRADE_TIME:
        return None
    if text.isdigit():
        return int(text)
    if trade_date and ":" in text and " " not in text:
        text = f"{str(trade_date).strip()} {text}"
    for form in _TRADE_TIME_FORMATS:
        try:
            return int(datetime.strptime(text, form).replace(tzinfo=INDIA).timestamp())
        except ValueError:
            continue
    try:
        clock = datetime.strptime(text, "%H:%M:%S").time()
    except ValueError:
        return None
    if not update_time:
        return None
    reference = datetime.fromtimestamp(update_time, tz=INDIA)
    moment = datetime.combine(reference.date(), clock, tzinfo=INDIA)
    if moment > reference + timedelta(minutes=5):
        moment -= timedelta(days=1)
    return int(moment.timestamp())

class NorenQuoteSource(BrokerQuoteSource):
    """
    Fetches quotes from a Noren deployment. A subclass sets BROKER_NAME and QUOTE_URL.

    Attributes:
        QUOTE_URL (str): The deployment's `GetQuotes` endpoint.
    """

    QUOTE_URL = None

    def fetch(self, client, handle, identity, received_at):
        token = str(handle["broker_token"]).strip()
        exchange = noren_exchange(identity)
        if exchange is None or not token:
            raise QuoteUnavailable(f"{self.BROKER_NAME} has no Noren exchange for segment {identity.get('segment')}")

        # A fresh dict each time: the API client writes the user id into the one it is given.
        response = client.post(url=self.QUOTE_URL, data={"exch": exchange, "token": token},
                               timeout=self.TIMEOUT_SECONDS)
        quote = (response or {}).get("data")
        if not isinstance(quote, dict):
            raise QuoteUnavailable(f"{self.BROKER_NAME} returned no quote for {exchange}|{token}: {str(quote)[:200]}")
        if str(quote.get("stat", "")).lower() != "ok":
            message = str(quote.get("emsg") or quote)
            if any(marker in message.lower() for marker in _AUTHENTICATION_MARKERS):
                raise NorenRefusal(f"{self.BROKER_NAME} refused the session: {message[:200]}")
            raise QuoteUnavailable(f"{self.BROKER_NAME} returned no quote for {exchange}|{token}: {message[:200]}")

        tick = contract_tick(self.BROKER_NAME, f"{exchange}|{token}", identity["exchange"], received_at)
        last_price = _number(quote.get("lp"))
        close = _number(quote.get("c"))
        update_time = _number(quote.get("lut"), int)

        depth = {"buy": [], "sell": []}
        for level in range(1, 6):
            for side, prefix in (("buy", "b"), ("sell", "s")):
                if quote.get(f"{prefix}p{level}") is not None:
                    depth[side].append({
                        "quantity": _number(quote.get(f"{prefix}q{level}"), int),
                        "price": _number(quote.get(f"{prefix}p{level}")),
                        "orders": _number(quote.get(f"{prefix}o{level}"), int),
                    })

        change = _number(quote.get("pc"))
        if change is None and last_price is not None and close:
            change = (last_price - close) * 100 / close

        tick.update({
            "mode": "full" if depth["buy"] or depth["sell"] else "quote",
            "last_price": last_price,
            "last_quantity": _number(quote.get("ltq"), int),
            "average_price": _number(quote.get("ap")),
            "volume": _number(quote.get("v"), int),
            "buy_quantity": _number(quote.get("tbq"), int),
            "sell_quantity": _number(quote.get("tsq"), int),
            "ohlc": {"open": _number(quote.get("o")), "high": _number(quote.get("h")),
                     "low": _number(quote.get("l")), "close": close},
            "change": change,
            "oi": _number(quote.get("oi"), int),
            "last_trade_time": _trade_time(quote.get("ltt"), quote.get("ltd"), update_time),
            "exchange_timestamp": update_time,
            "depth": depth,
        })
        return tick

    def is_authentication_error(self, exception):
        if isinstance(exception, NorenRefusal):
            return True
        text = str(exception).lower()
        return any(marker in text for marker in _AUTHENTICATION_MARKERS)
