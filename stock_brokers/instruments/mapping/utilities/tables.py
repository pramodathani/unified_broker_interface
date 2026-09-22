"""
The two tables the mapping writes, and the prefix of the mapping cache kept for them.

The mapping stage maps each broker's instrument snapshot into `unified.instruments` and `unified.broker_mappings`,
which `bin/unified/instruments/map` runs each day and the REST API reads. The names live here rather than in each
query: the writer in `base.py`, the index lookup in `crossref.py`, the duplicate merge in `collisions.py`, the resolver
in `resolution.py` and the mapping cache in `cache.py` read them from this module.
"""

# The master table: one row per real-world instrument.
MASTER = "unified.instruments"

# The dated table of which token each broker uses for each instrument.
BROKER_MAPPINGS = "unified.broker_mappings"

CONTRACT_SIZES = "unified.contract_sizes"

# The prefix of every Redis key the mapping cache keeps for these tables. Not `unified:mapping:`, because the cache's
# warm deletes every key under its prefix but the current date's, and `unified:mapping:meta` belongs to
# bin/unified/instruments/map' own cache.
MAPPING_CACHE_PREFIX = "unified:catalogue:"
