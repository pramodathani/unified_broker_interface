"""
Normalizing one broker's ticks into values comparable with every other broker's.

Every market feed already emits the same twenty keys,
but the same key does not mean the same thing across brokers. The token and exchange are in the
broker's own vocabulary; MCX quantities are lots at one broker and units at another; `close` is the
previous session's close at one broker and today's close after the bell at another; some timestamps
are missing or on a shifted clock; float32 prices carry noise in the last digits. A `TickNormalizer`
subclass states those facts about one broker, and this base class applies them.

The work is split so that the per-tick cost is arithmetic only:

- `feed_key` turns a tick's token into the broker token and canonical segments that
  `unified.broker_mappings` is searched with. It runs once per token per mapping date.
- `InstrumentPlan` is compiled from that lookup - the instrument id, its identity, and every
  per-field multiplier and flag - once per token per mapping date.
- `normalize` applies a plan to a tick, and runs on every tick.

Nothing here touches Redis or the database, so the same code serves the live service and is tested
offline.
"""

import json
from collections import namedtuple

from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, DERIVATIVE_SEGMENTS,
                                                                  INDEX_SEGMENTS, segments_of)

# What a tick's token resolves through: the broker token as stored in unified.broker_mappings,
# and the canonical segments the instrument can be in. The segments are not optional decoration -
# most brokers reuse one bare token across segments, so a lookup without them picks an arbitrary
# instrument. A broker whose ticks name the instrument by its order symbol rather than its token -
# Fyers - leaves broker_token None and sets order_symbol, which the resolver turns into the token.
FeedKey = namedtuple("FeedKey", ["broker_token", "segments", "order_symbol"], defaults=(None,))

# Quantity fields a broker may report in lots rather than units. "depth_quantity" stands for the
# quantity at every order book level.
QUANTITY_FIELDS = ("last_quantity", "volume", "buy_quantity", "sell_quantity", "depth_quantity",
                   "oi", "oi_day_high", "oi_day_low")

# How a broker reports a quantity field. "units" and "lots" are what they say. "broker_lots" is a
# figure in units by the broker's own lot size - Kotak's MCX last quantity is lots times Kotak's lot
# size, which for GOLD is 1 where the contract's is 100 - so it is divided by the broker's lot size and
# multiplied by the authoritative one.
BASIS_UNITS = "units"
BASIS_LOTS = "lots"
BASIS_BROKER_LOTS = "broker_lots"

# Where a broker's `close` may be taken as the previous session's close.
CLOSE_ALWAYS = "always"              # close is the previous close at every hour
CLOSE_BEFORE_SESSION_END = "before"  # the previous close during the session, today's close after it
CLOSE_NEVER = "never"                # close is something else, such as the last price

DEPTH_LEVELS = 5

def family_segments(exchanges, family):
    """
    The canonical segments for a family of instruments on some exchanges.

    Args:
        exchanges (list[str]): Canonical exchanges, for example ["nse"].
        family (str): "cash", "index", "cash_or_index" or "derivative".

    Returns:
        tuple[str]: Exchange-prefixed segment names.
    """
    bare = {
        "cash": CASH_SEGMENTS,
        "index": INDEX_SEGMENTS,
        "cash_or_index": CASH_SEGMENTS + INDEX_SEGMENTS,
        "derivative": DERIVATIVE_SEGMENTS,
    }[family]
    return tuple(segments_of(list(exchanges), bare))

class InstrumentPlan:
    """
    Everything needed to normalize one broker token's ticks, decided once rather than per tick.

    Attributes:
        instrument_id (str): The unified.instruments id.
        broker (str): The broker the token belongs to.
        broker_token (str): The token as stored in unified.broker_mappings.
        exchange (str): Canonical exchange.
        segment (str): Exchange-prefixed canonical segment.
        shape (str): "security", "future" or "option".
        session (Session): The window its ticks are accepted in.
        lot_size (int | None): Underlying units per lot, or None when unknown.
        multipliers (dict): Quantity field to the multiplier turning the broker's figure into units, or None when that field cannot be converted.
        price_decimals (int): Places prices are rounded to.
        negative_prices (bool): Whether a negative price is real (commodity futures have traded below zero).
        close_policy (str): One of CLOSE_ALWAYS, CLOSE_BEFORE_SESSION_END, CLOSE_NEVER.
        has_open_interest (bool): False for securities, whose open interest is meaningless.
        trusts_last_trade_time (bool): Whether the broker's last trade time is used.
        trusts_exchange_time (bool): Whether the broker's exchange timestamp is used.
        identity_json (str): The identity fields serialized once, without the enclosing braces, for splicing into every quote.
    """

    __slots__ = ("instrument_id", "broker", "broker_token", "exchange", "segment", "shape", "session",
                 "lot_size", "multipliers", "price_decimals", "negative_prices", "close_policy",
                 "has_open_interest", "trusts_last_trade_time", "trusts_exchange_time", "identity_json")

    def __init__(self, **values):
        for name in self.__slots__:
            setattr(self, name, values[name])

def identity_json(instrument_id, broker, broker_token, identity, lot_size):
    """
    The identity part of a unified quote, serialized once for an instrument.

    Args:
        instrument_id (str): The unified.instruments id.
        broker (str): The broker supplying the quote.
        broker_token (str): The broker's token for the instrument.
        identity (dict): The identity dict the mapping cache returns.
        lot_size (int | None): Underlying units per lot.

    Returns:
        str: A JSON object's members without the enclosing braces.
    """
    expiry = identity.get("expiry_date")
    strike = identity.get("strike_price")
    fields = {
        "instrument_id": instrument_id,
        "broker": broker,
        "broker_token": broker_token,
        "exchange": identity.get("exchange"),
        "segment": identity.get("segment"),
        "shape": identity.get("shape"),
        "symbol": identity.get("symbol"),
        "underlying_symbol": identity.get("underlying_symbol"),
        "expiry_date": expiry.isoformat() if hasattr(expiry, "isoformat") else expiry,
        "strike_price": float(strike) if strike is not None else None,
        "option_type": identity.get("option_type"),
        "lot_size": lot_size,
    }
    return json.dumps(fields, separators=(",", ":"))[1:-1]

class TickNormalizer:
    """
    Base class for one broker's tick normalization.

    A subclass implements `feed_key` and sets the class attributes that describe the broker. The
    defaults are the conservative reading: quantities in units, `close` not trusted as the previous
    close, both timestamps trusted.

    Attributes:
        BROKER_NAME (str): The broker this normalizer is for.
        LOT_FIELDS (dict): Exchange to the set of QUANTITY_FIELDS the broker reports in lots there.
        BROKER_LOT_FIELDS (dict): Exchange to the set of QUANTITY_FIELDS the broker reports as lots times its own lot size there.
        CLOSE_POLICY (dict): Exchange to one of the CLOSE_* policies. Exchanges absent use CLOSE_NEVER.
        TRUSTS_LAST_TRADE_TIME (bool): Whether the broker's last_trade_time is a true instant.
        TRUSTS_EXCHANGE_TIME (bool): Whether the broker's exchange_timestamp is a true instant.
    """

    BROKER_NAME = None
    LOT_FIELDS = {}
    BROKER_LOT_FIELDS = {}
    CLOSE_POLICY = {}
    TRUSTS_LAST_TRADE_TIME = True
    TRUSTS_EXCHANGE_TIME = True

    # A timestamp further than this before the tick was received is on a shifted clock or stale.
    MAXIMUM_TIMESTAMP_AGE_SECONDS = 7 * 86400
    # A timestamp further than this after the tick was received is on a shifted clock.
    MAXIMUM_TIMESTAMP_LEAD_SECONDS = 5

    def feed_key(self, instrument_token):
        """
        Turn the token a feed puts on its ticks into what the broker's mappings are searched with.

        Args:
            instrument_token (int | str): The tick's `instrument_token`.

        Returns:
            FeedKey | None: The key, or None for a token this normalizer cannot place.
        """
        raise NotImplementedError

    def tick_spelling(self, subscription_token):
        """
        A subscription-set token spelled the way the feed spells it on ticks.

        Plans are filed under the tick's spelling, because that is what the per-tick path looks up.
        A subscription set holds strings in the spelling the broker's quote feed subscribes with, which is
        not always the tick's: Kite ticks carry an integer, Dhan ticks a numeric segment code.

        Args:
            subscription_token (str): A member of `subscriptions_<broker>`.

        Returns:
            int | str | None: The tick's spelling, or None for a token this normalizer cannot place.
        """
        return subscription_token

    def quantity_basis(self, exchange, field):
        """
        Whether the broker reports a quantity field in lots or units on an exchange.

        Args:
            exchange (str): Canonical exchange.
            field (str): One of QUANTITY_FIELDS.

        Returns:
            str: BASIS_UNITS, BASIS_LOTS or BASIS_BROKER_LOTS.
        """
        if field in self.BROKER_LOT_FIELDS.get(exchange, ()):
            return BASIS_BROKER_LOTS
        if field in self.LOT_FIELDS.get(exchange, ()):
            return BASIS_LOTS
        return BASIS_UNITS

    def close_policy(self, exchange):
        """
        When the broker's `close` is the previous session's close on an exchange.

        Args:
            exchange (str): Canonical exchange.

        Returns:
            str: One of the CLOSE_* policies.
        """
        return self.CLOSE_POLICY.get(exchange, CLOSE_NEVER)

    def normalize(self, tick, plan, before_trading_close):
        """
        Apply a plan to one tick.

        Args:
            tick (dict): A tick as the broker's market feed published it.
            plan (InstrumentPlan): The compiled plan for the tick's token.
            before_trading_close (bool): Whether the tick was received before its session's close, for the close policy.

        Returns:
            dict | None: The normalized values, or None when the tick carries no usable last price. Keys are last_price, last_quantity, average_price, volume, buy_quantity, sell_quantity, open, high, low, reported_close, oi, oi_day_high, oi_day_low, last_trade_time, exchange_time, bids and asks, where bids and asks are lists of (price, quantity, orders) best first.
        """
        decimals = plan.price_decimals
        negative = plan.negative_prices

        last_price = tick.get("last_price")
        if last_price is None or last_price == 0 or (last_price < 0 and not negative):
            return None
        last_price = round(last_price, decimals)

        multipliers = plan.multipliers
        received_at = tick.get("received_at") or 0.0
        ohlc = tick.get("ohlc") or {}

        close = None
        policy = plan.close_policy
        if policy == CLOSE_ALWAYS or (policy == CLOSE_BEFORE_SESSION_END and before_trading_close):
            close = _price(ohlc.get("close"), decimals, negative)

        if plan.has_open_interest:
            oi = _quantity(tick.get("oi"), multipliers["oi"])
            oi_day_high = _quantity(tick.get("oi_day_high") or None, multipliers["oi_day_high"])
            oi_day_low = _quantity(tick.get("oi_day_low") or None, multipliers["oi_day_low"])
        else:
            oi = oi_day_high = oi_day_low = None

        depth = tick.get("depth") or {}
        depth_multiplier = multipliers["depth_quantity"]

        return {
            "last_price": last_price,
            "last_quantity": _quantity(tick.get("last_quantity"), multipliers["last_quantity"]),
            "average_price": _price(tick.get("average_price"), decimals, negative),
            "volume": _quantity(tick.get("volume"), multipliers["volume"]),
            "buy_quantity": _quantity(tick.get("buy_quantity"), multipliers["buy_quantity"]),
            "sell_quantity": _quantity(tick.get("sell_quantity"), multipliers["sell_quantity"]),
            "open": _price(ohlc.get("open"), decimals, negative),
            "high": _price(ohlc.get("high"), decimals, negative),
            "low": _price(ohlc.get("low"), decimals, negative),
            "reported_close": close,
            "oi": oi,
            "oi_day_high": oi_day_high,
            "oi_day_low": oi_day_low,
            "last_trade_time": self._instant(tick.get("last_trade_time"), received_at) if plan.trusts_last_trade_time else None,
            "exchange_time": self._instant(tick.get("exchange_timestamp"), received_at) if plan.trusts_exchange_time else None,
            "bids": _levels(depth.get("buy"), decimals, negative, depth_multiplier),
            "asks": _levels(depth.get("sell"), decimals, negative, depth_multiplier),
        }

    def _instant(self, value, received_at):
        """
        A broker timestamp as a true epoch, or None when it is missing or implausible.

        Brokers that stamp times on a shifted clock have that corrected in their market feed; what is
        left to catch here is a clock nobody has corrected yet, which shows as an instant days away
        from when the tick arrived.

        Args:
            value (float | int | None): Epoch seconds as the feed published them.
            received_at (float): When the feed decoded the tick.

        Returns:
            float | None: The instant, or None.
        """
        if not value:
            return None
        try:
            instant = float(value)
        except (TypeError, ValueError):
            return None
        if received_at and not (received_at - self.MAXIMUM_TIMESTAMP_AGE_SECONDS
                                <= instant <= received_at + self.MAXIMUM_TIMESTAMP_LEAD_SECONDS):
            return None
        return instant

def _price(value, decimals, negative):
    """
    A price rounded to the instrument's precision, or None for a missing, zero or impossible one.

    Rounding is what removes float32 noise - 2232.6001 from a feed decoding single precision floats
    is 2232.60 - and fixes every broker's figure to the same number of places.
    """
    if value is None or value == 0:
        return None
    if value < 0 and not negative:
        return None
    return round(value, decimals)

def _quantity(value, multiplier):
    """
    A quantity in whole underlying units, or None for a missing, negative or unconvertible one.
    """
    if value is None or multiplier is None:
        return None
    if value.__class__ is not int:
        try:
            value = int(round(value))
        except (TypeError, ValueError):
            return None
    if value < 0:
        return None
    if multiplier.__class__ is int:
        return value * multiplier
    return int(round(value * multiplier))

def _levels(levels, decimals, negative, multiplier):
    """
    Order book levels with a price and a quantity, best first, at most DEPTH_LEVELS.

    Brokers pad an empty book with zero rows, some do and some do not; dropping every level without
    both a price and a quantity makes an empty level mean the same thing everywhere.
    """
    if not levels:
        return []
    kept = []
    for level in levels:
        price = level.get("price")
        quantity = level.get("quantity")
        if not price or not quantity:
            continue
        price = _price(price, decimals, negative)
        units = _quantity(quantity, multiplier)
        if price is None:
            continue
        orders = level.get("orders")
        if orders is not None and orders.__class__ is not int:
            try:
                orders = int(round(orders))
            except (TypeError, ValueError):
                orders = None
        kept.append((price, units, orders))
        if len(kept) == DEPTH_LEVELS:
            break
    return kept
