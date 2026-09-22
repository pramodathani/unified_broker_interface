"""
An instrument's stored history: its candles from `unified.price_history` and its ticks from `unified.ticks`, every
relation named through `stock_brokers.instruments.historical.utilities.unified.tables`.

**Adjustment applies only to cash-like instruments.** Splits, bonuses and demergers are corrected only
for the segments in `ADJUSTABLE_SEGMENTS` - equities, exchange traded funds and investment trusts. Those
are stored unadjusted and adjusted on read from the confirmed rows of the adjustment factors:

- candles through `adjusted_bars()`, which with `known_as_of` applies only the factors
  known by that date, so a backtest sees what a chart showed then;
- ticks through the `ticks_adjusted` view.

Every other instrument - futures and options, including those on an adjustable equity, indices, bonds,
currencies, commodities and mutual funds - is stored exactly as the broker served it, and is read from
the raw tables whatever `adjusted` says. Both responses say which they are: `adjustable`, and
`price_basis` of `adjusted`, `unadjusted` or `as_served`.

**Candles are cached, ticks are not.** `candles()` keeps every answer in Redis through
`utilities/price_cache.py`, which holds the widest range read for each series and slices later requests
out of it, so a repeated request makes no database query; `source` in the answer says which it was.
`tick_stream()` streams straight from the database, because a period of ticks is far too large to keep.
"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import text

from stock_brokers.instruments.historical.utilities.unified import tables
from stock_brokers.instruments.historical.utilities.unified.sources import LOADED_INTERVALS
from stock_brokers.instruments.mapping.utilities.segments import is_adjustable
from stock_brokers.instruments.ticks.utilities.pipeline import TICK_COLUMNS
from unified_broker_interface.utilities.instrument_identity import INDIA, RequestError, identity_to_json
from unified_broker_interface.utilities.price_cache import PriceCache

# A plain JSON answer holds every candle in memory, so an intraday range is capped; daily is not.
MAX_INTRADAY_DAYS = 366

TICK_STREAM_ROWS = 5000

# The columns every candle answer carries, with price_factor added when the prices are adjusted.
CANDLE_COLUMNS = [
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "oi",
]

def price_basis(segment, adjusted):
    """
    Whether an instrument's prices can be adjusted, and what the response's prices are.

    Returns a pair `(adjustable, basis)`.

    - `segment` is the instrument's exchange-prefixed segment.
    - `adjusted` is what the request asked for.
    """
    adjustable = segment != "uncategorised" and is_adjustable(segment)
    if not adjustable:
        return False, "as_served"
    return True, "adjusted" if adjusted else "unadjusted"

def _india_midnight(day):
    """
    The instant an India calendar day begins.

    - `day` is the date.
    """
    return datetime.combine(day, time.min, tzinfo=INDIA)

def _read_candles(engine, instrument_id, interval, basis, from_date, to_date, known_as_of):
    """
    One series' candles between two dates, read from the database in the shape the answer sends them.

    - `engine` is the SQLAlchemy engine.
    - `instrument_id` is the unified instrument id, as text.
    - `interval` is the stored interval name.
    - `basis` is the price basis, which decides whether the adjusted function or the raw table is read.
    - `from_date` and `to_date` bound the range, both inclusive, as India calendar days.
    - `known_as_of` limits the factors applied to those known by that date, or None for all.
    """
    parameters = {
        "instrument_id": instrument_id,
        "interval": interval,
        "start": _india_midnight(from_date),
        "end": _india_midnight(to_date + timedelta(days=1)),
    }
    if basis == "adjusted":
        parameters["known_as_of"] = known_as_of
        statement = text(
            'SELECT "time", open, high, low, close, volume, oi, price_factor '
            f"FROM {tables.ADJUSTED_BARS}(CAST(:instrument_id AS uuid), :interval, :start, :end, "
            "CAST(:known_as_of AS date))")
    else:
        statement = text(
            f'SELECT "time", open, high, low, close, volume, oi FROM {tables.PRICE_HISTORY} '
            'WHERE instrument_id = CAST(:instrument_id AS uuid) AND "interval" = :interval '
            '  AND "time" >= :start AND "time" < :end ORDER BY "time"')

    with engine.connect() as connection:
        rows = connection.execute(statement, parameters).all()

    def number(value):
        return float(value) if value is not None else None

    series = []
    for row in rows:
        candle = [row.time.isoformat(), number(row.open), number(row.high), number(row.low), number(row.close),
                  row.volume, row.oi]
        if basis == "adjusted":
            candle.append(number(row.price_factor))
        series.append(candle)
    return series

def candles(engine, cache, identity, interval, from_date, to_date, adjusted, known_as_of):
    """
    One instrument's candles between two dates, inclusive, as a JSON-ready answer.

    Served from the Redis copy when it covers the range asked for, and from the database otherwise,
    which leaves a copy behind for the next request. `source` in the answer says which happened.

    - `engine` is the SQLAlchemy engine.
    - `cache` is the Redis client the copy is kept in.
    - `identity` is the instrument's identity.
    - `interval` is one of `LOADED_INTERVALS`.
    - `from_date` and `to_date` bound the range, both inclusive, as India calendar days.
    - `adjusted` asks for adjusted prices, which only an adjustable instrument has.
    - `known_as_of` limits the factors applied to those known by that date, or None for all.
    """
    if interval not in LOADED_INTERVALS:
        raise RequestError(f"interval must be one of {', '.join(LOADED_INTERVALS)}")
    if to_date < from_date:
        raise RequestError("to must not be before from")
    maximum_days = None if interval == "day" else MAX_INTRADAY_DAYS
    if maximum_days is not None and (to_date - from_date).days > maximum_days:
        raise RequestError(f"an intraday range may span at most {maximum_days} days")

    adjustable, basis = price_basis(identity["segment"], adjusted)
    columns = list(CANDLE_COLUMNS)
    if basis == "adjusted":
        columns.append("price_factor")

    instrument_id = str(identity["instrument_id"])
    cached = PriceCache(cache, instrument_id, interval, basis,
                        known_as_of if basis == "adjusted" else None, columns)
    cached.load()
    if not cached.covers(from_date, to_date):
        query_from, query_to = cached.query_range(from_date, to_date, maximum_days)
        cached.replace(query_from, query_to,
                       _read_candles(engine, instrument_id, interval, basis, query_from, query_to, known_as_of))
    series = cached.between(_india_midnight(from_date), _india_midnight(to_date + timedelta(days=1)))

    return {
        **identity_to_json(identity),
        "interval": interval,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "adjustable": adjustable,
        "price_basis": basis,
        "known_as_of": known_as_of.isoformat() if basis == "adjusted" and known_as_of else None,
        "source": "cache" if cached.loaded else "database",
        "columns": columns,
        "candles": series,
    }

def _tick_document(row):
    """
    One tick row in the unified quote document's field names, with the book nested.

    - `row` is the row's mapping.
    """
    def number(value):
        return float(value) if value is not None else None

    def instant(value):
        return value.astimezone(timezone.utc).isoformat() if value is not None else None

    depth = {"buy": [], "sell": []}
    for side, prefix in (("buy", "bid"), ("sell", "ask")):
        for level in range(1, 6):
            price = row[f"{prefix}{level}_price"]
            if price is None:
                continue
            depth[side].append({"price": number(price), "quantity": row[f"{prefix}{level}_quantity"],
                                "orders": row[f"{prefix}{level}_orders"]})
    return {
        "time": instant(row["time"]),
        "broker": row["broker"],
        "last_price": number(row["last_price"]),
        "average_price": number(row["average_price"]),
        "ohlc": {"open": number(row["open"]), "high": number(row["high"]), "low": number(row["low"])},
        "previous_close": number(row["previous_close"]),
        "change_percent": number(row["change_percent"]),
        "last_quantity": row["last_quantity"],
        "volume": row["volume"],
        "buy_quantity": row["buy_quantity"],
        "sell_quantity": row["sell_quantity"],
        "oi": row["oi"],
        "oi_day_high": row["oi_day_high"],
        "oi_day_low": row["oi_day_low"],
        "lot_size": row["lot_size"],
        "depth": depth,
        "last_trade_time": instant(row["last_trade_time"]),
        "exchange_time": instant(row["exchange_time"]),
    }

def tick_stream(engine, identity, start, end, adjusted):
    """
    One instrument's ticks in a period, as the response headers and a generator of tick documents.

    The query is opened with a server-side cursor, so a long period is read as it is sent rather than
    loaded first.

    - `engine` is the SQLAlchemy engine.
    - `identity` is the instrument's identity.
    - `start` and `end` bound the period, `start <= time < end`, as aware datetimes.
    - `adjusted` asks for adjusted prices, which only an adjustable instrument has.
    """
    if end <= start:
        raise RequestError("end must be after start")

    adjustable, basis = price_basis(identity["segment"], adjusted)
    table = tables.TICKS_ADJUSTED if basis == "adjusted" else tables.TICKS
    columns = ", ".join(f'"{column}"' for column in TICK_COLUMNS if column != "instrument_id")
    statement = text(f"SELECT {columns} FROM {table} "
                     f'WHERE instrument_id = CAST(:instrument_id AS uuid) AND "time" >= :start AND "time" < :end '
                     f'ORDER BY "time"')
    parameters = {"instrument_id": str(identity["instrument_id"]), "start": start, "end": end}

    def generate():
        with engine.connect().execution_options(stream_results=True, max_row_buffer=TICK_STREAM_ROWS) as connection:
            for row in connection.execute(statement, parameters):
                yield _tick_document(row._mapping)

    headers = {
        "X-Instrument-Id": str(identity["instrument_id"]),
        "X-Adjustable": "true" if adjustable else "false",
        "X-Price-Basis": basis,
        "X-Start": start.isoformat(),
        "X-End": end.isoformat(),
    }
    return headers, generate()
