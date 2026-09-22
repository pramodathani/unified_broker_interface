"""
The tables and views the unified price history reads and writes.

`bin/unified/instruments/price_history` builds one price history per unified instrument in the `unified` schema, and the REST
API's `/prices` and `/ticks` read it. The names live here rather than in each query: the loader, the corrections, the
factors, the resolver, the checks and the API read them from this module. Resolving a series also goes through the
mapping resolver, whose tables are named by `stock_brokers.instruments.mapping.utilities.tables`.
"""


# Every instrument's bars under its unified id.
PRICE_HISTORY = "unified.price_history"

# Every broker series that feeds the history, and how it was matched to its instrument.
PRICE_HISTORY_SOURCES = "unified.price_history_sources"

# Multipliers undoing an adjustment a broker had already applied to a series it served, and their ranges.
PRICE_HISTORY_CORRECTIONS = "unified.price_history_corrections"
CORRECTION_RANGES = "unified.correction_ranges"

# Split, bonus and demerger factors, their ranges, and the history read through them.
ADJUSTMENT_FACTORS = "unified.adjustment_factors"
ADJUSTMENT_RANGES = "unified.adjustment_ranges"
PRICE_HISTORY_ADJUSTED = "unified.price_history_adjusted"
ADJUSTED_BARS = "unified.adjusted_bars"

# Where the Yahoo Finance fetch has got to.
YAHOO_FETCH_STATE = "unified.yahoo_fetch_state"

# The mapped instruments and broker tokens a series is resolved against.
MASTER = "unified.instruments"
BROKER_MAPPINGS = "unified.broker_mappings"

# The persisted ticks, and the same read through the adjustment ranges.
TICKS = "unified.ticks"
TICKS_ADJUSTED = "unified.ticks_adjusted"
