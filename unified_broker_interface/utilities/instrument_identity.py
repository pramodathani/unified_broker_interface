"""
Reading the instrument endpoints' query parameters: which instrument, which segment, which dates.

Every instrument endpoint that acts on one instrument accepts it in either of two spellings:

- `instrument_id`, the unified.instruments id; or
- `exchange` and `segment`, plus the identity fields that segment's shape calls for - `symbol` for a
  security, `underlying_symbol` and `expiry_date` for a future, and those plus `strike_price` and
  `option_type` for an option.

This module only reads and checks the parameters, answering with an `InstrumentQuery`. Turning a query
into an id needs the instrument catalogue, which knows the names as they are stored.

A parameter that cannot be used raises `RequestError`, which carries the HTTP status the blueprint
answers with.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from stock_brokers.instruments.mapping.utilities.segments import (CANONICAL_EXCHANGES, CANONICAL_SEGMENTS,
                                                                  segment_shape, segment_value)

INDIA = timezone(timedelta(hours=5, minutes=30))

# The segment an instrument the mapping could not place on an exchange lands in, stored unprefixed.
UNCATEGORISED = "uncategorised"
UNKNOWN_EXCHANGE = "unknown"

IDENTITY_FIELDS = {
    "security": ("symbol",),
    "future": ("underlying_symbol", "expiry_date"),
    "option": ("underlying_symbol", "expiry_date", "strike_price", "option_type"),
}

OPTION_TYPES = ("CE", "PE")

_BARE_SEGMENTS = {name for name, _ in CANONICAL_SEGMENTS}

class RequestError(Exception):
    """
    A request the instrument endpoints cannot answer as asked.

    Attributes:
        message (str): What was wrong, returned to the caller.
        status (int): The HTTP status to answer with.
    """

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status

class InstrumentQuery:
    """
    One instrument as a request named it: either an id, or a segment and identity fields.

    Attributes:
        instrument_id (str | None): The id, when the request gave one.
        exchange (str | None): The exchange, when the request named the instrument by identity.
        segment (str | None): The exchange-prefixed segment.
        shape (str | None): The segment's shape.
        fields (dict): The identity fields, with names upper-cased, the expiry as a date and the strike as a Decimal.
    """

    def __init__(self, instrument_id=None, exchange=None, segment=None, shape=None, fields=None):
        self.instrument_id = instrument_id
        self.exchange = exchange
        self.segment = segment
        self.shape = shape
        self.fields = fields or {}

    @property
    def name(self):
        """The upper-cased symbol or underlying the instrument is catalogued under."""
        return self.fields.get("symbol") or self.fields.get("underlying_symbol")

def parse_date(raw, name, default=None):
    """
    A `YYYY-MM-DD` parameter as a date.

    - `raw` is the parameter's value, or None when absent.
    - `name` is the parameter's name, used in the error message.
    - `default` is returned when the parameter is absent.
    """
    if raw in (None, ""):
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise RequestError(f"{name} must be a date in YYYY-MM-DD format")

def parse_datetime(raw, name):
    """
    A date or date and time parameter as a timezone-aware datetime.

    Accepts `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`, `YYYY-MM-DD HH:MM:SS` and ISO 8601 with a `T` or an offset.
    A value without an offset is India time, the exchanges' own clock.

    - `raw` is the parameter's value.
    - `name` is the parameter's name, used in the error message.
    """
    if raw in (None, ""):
        raise RequestError(f"{name} is required")
    text = raw.strip().replace("Z", "+00:00")
    try:
        if len(text) == 10:
            moment = datetime.combine(date.fromisoformat(text), time.min)
        else:
            moment = datetime.fromisoformat(text)
    except ValueError:
        raise RequestError(f"{name} must be a date or date and time, such as 2026-09-11 or 2026-09-11 09:15:00")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=INDIA)
    return moment

def parse_bool(raw, name, default):
    """
    A `true`/`false` parameter.

    - `raw` is the parameter's value, or None when absent.
    - `name` is the parameter's name, used in the error message.
    - `default` is returned when the parameter is absent.
    """
    if raw in (None, ""):
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise RequestError(f"{name} must be true or false")

def parse_int(raw, name, default, minimum, maximum):
    """
    A whole number parameter within bounds.

    - `raw` is the parameter's value, or None when absent.
    - `name` is the parameter's name, used in the error message.
    - `default` is returned when the parameter is absent.
    - `minimum` and `maximum` bound the accepted value.
    """
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RequestError(f"{name} must be a whole number")
    if not minimum <= value <= maximum:
        raise RequestError(f"{name} must be between {minimum} and {maximum}")
    return value

def parse_exchange(raw, allow_all=False):
    """
    The `exchange` parameter, lower-cased, or `all` where that is allowed.

    - `raw` is the parameter's value.
    - `allow_all` accepts `all`.
    """
    if not raw:
        raise RequestError("exchange is required")
    exchange = raw.strip().lower()
    if allow_all and exchange == "all":
        return exchange
    if exchange not in CANONICAL_EXCHANGES and exchange != UNKNOWN_EXCHANGE:
        choices = ", ".join(CANONICAL_EXCHANGES + ["all"] if allow_all else CANONICAL_EXCHANGES)
        raise RequestError(f"exchange must be one of {choices}")
    return exchange

def parse_segment(exchange, raw, allow_all=False):
    """
    The `segment` parameter as the exchange-prefixed value unified.instruments stores.

    Accepts the stored value (`nse_equities`) or the bare name (`equities`), which is prefixed with the
    exchange. `uncategorised` is stored unprefixed and belongs to the `unknown` exchange.

    Returns a pair of the exchange, which `uncategorised` may change to `unknown`, and the segment.

    - `exchange` is the parsed exchange.
    - `raw` is the parameter's value.
    - `allow_all` accepts `all`.
    """
    if not raw:
        raise RequestError("segment is required")
    segment = raw.strip().lower()
    if allow_all and segment == "all":
        return exchange, segment
    if segment == UNCATEGORISED:
        return UNKNOWN_EXCHANGE, segment
    if exchange == "all":
        raise RequestError("a single segment needs a single exchange")
    bare = segment[len(exchange) + 1:] if segment.startswith(f"{exchange}_") else segment
    if bare not in _BARE_SEGMENTS:
        raise RequestError(f"segment {raw!r} is not a segment of {exchange}; see /api/instruments/segments")
    return exchange, segment_value(exchange, bare)

def shape_of(segment):
    """
    The shape of an exchange-prefixed segment.

    - `segment` is the exchange-prefixed segment, or `uncategorised`.
    """
    if segment == UNCATEGORISED:
        return "security"
    return segment_shape(segment.partition("_")[2])

def parse_instrument(args):
    """
    The instrument a request names, by id or by segment and identity fields.

    - `args` is the request's query parameters.
    """
    raw_id = args.get("instrument_id")
    if raw_id:
        try:
            return InstrumentQuery(instrument_id=str(uuid.UUID(raw_id.strip())))
        except ValueError:
            raise RequestError("instrument_id must be a UUID")

    if not args.get("exchange") and not args.get("segment"):
        raise RequestError("give instrument_id, or exchange, segment and the identity fields")

    exchange = parse_exchange(args.get("exchange") or (UNKNOWN_EXCHANGE if args.get("segment") == UNCATEGORISED else None))
    exchange, segment = parse_segment(exchange, args.get("segment"))
    shape = shape_of(segment)

    fields = {}
    for field in IDENTITY_FIELDS[shape]:
        raw = args.get(field)
        if raw in (None, ""):
            raise RequestError(f"a {shape} segment needs {', '.join(IDENTITY_FIELDS[shape])}")
        fields[field] = raw.strip()

    for field in ("symbol", "underlying_symbol"):
        if field in fields:
            fields[field] = fields[field].upper()
    if "expiry_date" in fields:
        fields["expiry_date"] = parse_date(fields["expiry_date"], "expiry_date")
    if "strike_price" in fields:
        try:
            fields["strike_price"] = Decimal(fields["strike_price"])
        except InvalidOperation:
            raise RequestError("strike_price must be a number")
    if "option_type" in fields:
        fields["option_type"] = fields["option_type"].upper()
        if fields["option_type"] not in OPTION_TYPES:
            raise RequestError("option_type must be CE or PE")

    return InstrumentQuery(exchange=exchange, segment=segment, shape=shape, fields=fields)

def identity_to_json(identity):
    """
    An identity as the instrument endpoints return it.

    The same field names and value spellings the unified quote document uses: the expiry as ISO text
    and the strike as a number.

    - `identity` is an identity dict from the mapping cache or unified.instruments.
    """
    expiry = identity.get("expiry_date")
    strike = identity.get("strike_price")
    return {
        "instrument_id": str(identity["instrument_id"]),
        "exchange": identity.get("exchange"),
        "segment": identity.get("segment"),
        "shape": identity.get("shape"),
        "symbol": identity.get("symbol"),
        "underlying_symbol": identity.get("underlying_symbol"),
        "expiry_date": expiry.isoformat() if hasattr(expiry, "isoformat") else expiry,
        "strike_price": float(strike) if strike is not None else None,
        "option_type": identity.get("option_type"),
    }
