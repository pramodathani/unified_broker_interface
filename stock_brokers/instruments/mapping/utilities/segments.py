"""
Canonical segment vocabulary for the instrument mapping layer.

The vocabulary declares every segment that a broker adapter may classify a raw row into, in the order that segments must appear in each broker's rules file under ``stock_brokers/instruments/mapping/utilities/rules/``. The order is by asset class first — fixed income, equities, currencies, commodities — and within each asset class by instrument kind: simple instruments, futures, options, indices, index futures, index options. The catch-all segments come last: mutual funds, exchange traded funds, investment trusts, and the uncategorised buckets.

Segment values stored in ``unified.instruments`` are exchange-prefixed, for example ``nse_equities`` and ``bse_equity_options``, produced by ``segment_value``.

``MAPPED_BROKERS`` lives here too, because the order the brokers are mapped in is a fact about mapping rather than about downloading, and several modules of this package import it.
"""

MAPPED_BROKERS = [
    "dhan",
    "kotak",
    "groww",
    "stoxkart",
    "fyers",
    "wisdom_capital",
    "indmoney",
    "flattrade",
    "shoonya",
    "zerodha",
]

CANONICAL_EXCHANGES = [
    "nse",
    "bse",
    "mcx",
    "ncdex",
]

CANONICAL_SEGMENTS = [
    ("fixed_income", "security"),
    ("fixed_income_futures", "future"),
    ("fixed_income_options", "option"),
    ("fixed_income_indices", "security"),
    ("fixed_income_index_futures", "future"),
    ("fixed_income_index_options", "option"),
    ("equities", "security"),
    ("equity_futures", "future"),
    ("equity_options", "option"),
    ("equity_indices", "security"),
    ("equity_index_futures", "future"),
    ("equity_index_options", "option"),
    ("currencies", "security"),
    ("currency_futures", "future"),
    ("currency_options", "option"),
    ("currency_indices", "security"),
    ("currency_index_futures", "future"),
    ("currency_index_options", "option"),
    ("commodities", "security"),
    ("commodity_futures", "future"),
    ("commodity_options", "option"),
    ("commodity_indices", "security"),
    ("commodity_index_futures", "future"),
    ("commodity_index_options", "option"),
    ("mutual_funds", "security"),
    ("exchange_traded_funds", "security"),
    ("investment_trusts", "security"),
    ("uncategorised", "security"),
]

_SEGMENT_SHAPES = {}
for segment_name, segment_shape in CANONICAL_SEGMENTS:
    _SEGMENT_SHAPES[segment_name] = segment_shape

_SEGMENT_ORDER = {}
for segment_position, (segment_name, _) in enumerate(CANONICAL_SEGMENTS):
    _SEGMENT_ORDER[segment_name] = segment_position

_EXCHANGE_ORDER = {}
for exchange_position, exchange_name in enumerate(CANONICAL_EXCHANGES):
    _EXCHANGE_ORDER[exchange_name] = exchange_position


def segment_value(exchange, bare_segment):
    """
    Build the exchange-prefixed segment value stored in the mapped tables.

    Args:
        exchange (str): Canonical lowercase exchange name, for example "nse".
        bare_segment (str): Bare segment name from CANONICAL_SEGMENTS, for example "equities".

    Returns:
        str: The prefixed segment value, for example "nse_equities".
    """
    return f"{exchange}_{bare_segment}"


def segment_shape(bare_segment):
    """
    Look up the shape declared for a bare segment name.

    Args:
        bare_segment (str): Bare segment name from CANONICAL_SEGMENTS.

    Returns:
        str: The segment's shape, one of "security", "future", or "option".

    Raises:
        ValueError: If bare_segment is not part of the canonical vocabulary.
    """
    if bare_segment not in _SEGMENT_SHAPES:
        raise ValueError(f"{bare_segment!r} is not a canonical segment name")
    return _SEGMENT_SHAPES[bare_segment]


def segment_rank(exchange, bare_segment):
    """
    Compute the ordering rank of one configured segment.

    The rank pairs the segment's position in the canonical vocabulary with the exchange's position in the canonical exchange list, so that a rules file listing segments in canonical order yields non-decreasing ranks. Config validation uses this to reject a rules file whose segments are out of order.

    Args:
        exchange (str): Canonical lowercase exchange name.
        bare_segment (str): Bare segment name from CANONICAL_SEGMENTS.

    Returns:
        tuple: A (segment_position, exchange_position) pair of ints.
    """
    return (_SEGMENT_ORDER[bare_segment], _EXCHANGE_ORDER[exchange])


def split_segment_value(value):
    """
    Split an exchange-prefixed segment value into its exchange and bare name.

    Args:
        value (str): Prefixed segment value, for example "nse_equities".

    Returns:
        tuple: An (exchange, bare_segment) pair, for example ("nse", "equities").
    """
    exchange, _, bare_segment = value.partition("_")
    return exchange, bare_segment


# Families of segments, for a caller that knows what kind of instrument it is holding but not which
# segment the mapping put it in. A broker's price table says "an NSE cash scrip" or "an NSE index",
# never "nse_exchange_traded_funds" - so resolving one of its series means searching every segment
# of that kind on that exchange.
CASH_SEGMENTS = (
    "equities",
    "exchange_traded_funds",
    "investment_trusts",
    "mutual_funds",
    "fixed_income",
    "uncategorised",
)

INDEX_SEGMENTS = (
    "equity_indices",
    "fixed_income_indices",
    "currency_indices",
    "commodity_indices",
)

DERIVATIVE_SEGMENTS = tuple(
    name for name, shape in CANONICAL_SEGMENTS if shape in ("future", "option")
)

# The segments whose prices change at a split, bonus or demerger, and so are stored unadjusted with
# adjustment factors kept beside them. Everything else is stored as the broker served it.
ADJUSTABLE_SEGMENTS = (
    "equities",
    "exchange_traded_funds",
    "investment_trusts",
)


def segments_of(exchanges, bare_segments):
    """
    Build the prefixed segment values for every combination of exchange and bare segment.

    Args:
        exchanges (str | list[str]): One canonical exchange name or several, for example "nse".
        bare_segments (tuple[str]): Bare segment names, usually one of the families above.

    Returns:
        list[str]: The prefixed values, for example ["nse_equities", "nse_exchange_traded_funds"].
    """
    if isinstance(exchanges, str):
        exchanges = [exchanges]
    return [segment_value(exchange, bare) for exchange in exchanges for bare in bare_segments]


def is_adjustable(segment):
    """
    Whether an exchange-prefixed segment is one whose prices are stored unadjusted with factors.

    Args:
        segment (str): A prefixed segment value, for example "nse_equities".

    Returns:
        bool: True for equities, exchange traded funds and investment trusts on any exchange.
    """
    return split_segment_value(segment)[1] in ADJUSTABLE_SEGMENTS
