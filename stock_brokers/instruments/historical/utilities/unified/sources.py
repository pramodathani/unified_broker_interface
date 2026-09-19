"""
Which broker supplies which instrument's prices, and on what basis.

The unified table does not blend brokers. For each instrument and interval one broker is the
primary source, and its series - several of them, when the broker's token for the instrument has
changed - are stitched together by time. A second broker may supply only whole trading days the
primary is missing, and only after agreeing with the primary on the days both have.

The choice of primary follows from what each broker's stored prices are, measured against the
stored data on 2026-09-13:

- flattrade serves daily and intraday history, NSE from December 2019 and BSE from March 2020, and is
  the closest to raw of any broker: its BSE daily bars have been raw in every case checked. Its NSE
  daily bars are not uniformly so - raw across some corporate actions, already adjusted across others
  (PIDILITIND's 2025 bonus, PGIL's of 2026-09-11) - which the factor builder copes with and `verify`
  reports; see the unified price history guide.
- wisdom_capital serves BSE intraday bars unadjusted from September 2025, including the 20, 45
  and 180 minute intervals nobody else has.
- zerodha, dhan, indmoney and fyers adjust their history, each with their own factors and each at
  their own time, so for equities they are not used as a source here. For indices, where there is
  nothing to adjust, zerodha's history is the deepest, back to 2005.
- shoonya is adjusted inconsistently, even within one series, and is not used.

Dhan's intraday bars appear unadjusted too, but that rests on one sample, so dhan stays out of the
policy until `verify` has classified its intraday series against confirmed factors.
"""

from stock_brokers.instruments.mapping.utilities.segments import (CASH_SEGMENTS, DERIVATIVE_SEGMENTS,
                                                                  INDEX_SEGMENTS, is_adjustable)

# Brokers whose stored prices have been verified to be unadjusted, by exchange and interval kind.
# A broker absent here is taken to serve adjusted prices, which rules it out as a source for the
# segments stored unadjusted.
UNADJUSTED = {
    ("flattrade", "nse", "day"),
    ("flattrade", "bse", "day"),
    ("flattrade", "nse", "intraday"),
    ("flattrade", "bse", "intraday"),
    ("wisdom_capital", "bse", "intraday"),
}

# Minutes in each intraday interval name the brokers store.
INTRADAY_MINUTES = {
    "1minute": 1, "2minute": 2, "3minute": 3, "4minute": 4, "5minute": 5, "10minute": 10,
    "15minute": 15, "20minute": 20, "25minute": 25, "30minute": 30, "45minute": 45,
    "60minute": 60, "120minute": 120, "180minute": 180, "240minute": 240,
}

# Intervals only wisdom_capital serves, for which it is the primary source on BSE.
WISDOM_ONLY_INTERVALS = ("20minute", "45minute", "180minute")

# A gap-filling broker must agree with the primary on at least this share of the bars both have.
GAP_FILL_AGREEMENT = 0.995

# The intervals `bin/unified/historical_prices load` accepts. The daily timer loads only "day"; intraday is
# loaded by hand until there is room for it - see the unified price history guide.
LOADED_INTERVALS = ("day",) + tuple(INTRADAY_MINUTES)

def interval_kind(interval):
    """
    Whether an interval is daily or intraday, in the terms `UNADJUSTED` uses.

    Args:
        interval (str): A stored interval name, for example "day" or "15minute".

    Returns:
        str | None: "day", "intraday", or None for week and month bars, which are not loaded.
    """
    if interval == "day":
        return "day"
    if interval in INTRADAY_MINUTES:
        return "intraday"
    return None

def segment_family(segment):
    """
    The family a canonical segment belongs to.

    Args:
        segment (str): A prefixed segment, for example "nse_equities".

    Returns:
        str | None: "cash", "index" or "derivative", or None for segments nothing is loaded for.
    """
    for family, members in (("cash", CASH_SEGMENTS), ("index", INDEX_SEGMENTS),
                            ("derivative", DERIVATIVE_SEGMENTS)):
        for member in members:
            if segment.endswith("_" + member) or segment == member:
                return family
    return None

def price_basis(segment):
    """
    How prices are stored for a segment.

    Args:
        segment (str): A prefixed segment.

    Returns:
        str: "unadjusted" for equities, exchange traded funds and investment trusts, "as_served"
            for everything else.
    """
    return "unadjusted" if is_adjustable(segment) else "as_served"

def sources_for(exchange, segment, interval):
    """
    The brokers that may supply one instrument's bars, in order.

    Args:
        exchange (str): The canonical exchange, for example "nse".
        segment (str): The prefixed segment.
        interval (str): The stored interval name.

    Returns:
        list[tuple[str, str]]: (broker, role) pairs, the primary first and any gap-fill brokers
            after it. Empty when no broker is allowed to supply the instrument at this interval.
    """
    kind = interval_kind(interval)
    family = segment_family(segment)
    if kind is None or family is None:
        return []

    if family == "cash":
        if exchange == "bse" and interval in WISDOM_ONLY_INTERVALS:
            candidates = [("wisdom_capital", "primary")]
        elif exchange == "bse" and kind == "intraday":
            candidates = [("flattrade", "primary"), ("wisdom_capital", "gap_fill")]
        else:
            candidates = [("flattrade", "primary")]
        if is_adjustable(segment):
            allowed = []
            for broker, role in candidates:
                if (broker, exchange, kind) in UNADJUSTED:
                    allowed.append((broker, role))
            return allowed
        return candidates

    if family == "index":
        if kind == "day":
            return [("zerodha", "primary"), ("dhan", "gap_fill"), ("flattrade", "gap_fill")]
        if interval in ("15minute", "30minute", "60minute"):
            return [("zerodha", "primary")]
        return [("flattrade", "primary")]

    # Futures, options, currencies and commodities: there is nothing to adjust, so the deepest and
    # most complete broker leads. No derivative bars are stored yet, so this is policy only.
    return [("zerodha", "primary"), ("dhan", "gap_fill"), ("flattrade", "gap_fill")]

def brokers_for_interval(interval):
    """
    Every broker that is primary or gap-fill for some segment at an interval.

    Args:
        interval (str): The stored interval name.

    Returns:
        list[str]: Broker names, in a stable order.
    """
    brokers = []
    for exchange in ("nse", "bse", "mcx"):
        for segment in (f"{exchange}_equities", f"{exchange}_equity_indices", f"{exchange}_equity_futures"):
            for broker, _ in sources_for(exchange, segment, interval):
                if broker not in brokers:
                    brokers.append(broker)
    return brokers
