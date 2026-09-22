# Instrument mapping

The [instrument masters](instruments.md) subsystem gives every broker's daily file its own table.
This one answers the question those tables cannot: which rows, across ten brokers, are the same
real-world instrument.

It writes two tables. `unified.instruments` holds one row per instrument, whoever lists it.
`unified.broker_mappings` holds one row per broker per day saying which token that broker uses
for it. With both in place, one instrument id is enough to place an order at any broker, or to
compare a price series from one against a position held at another.

That second table also carries an `attributes` column, holding the extra columns a broker's own
instrument file publishes beyond the token, the symbols, the lot size and the tick size: the ISIN,
the series, the freeze quantity, the price band and so on, under the shared names
[`raw_attributes.py`][stock_brokers.instruments.mapping.utilities.raw_attributes] gives them. They
are read here, while the raw row is in hand, because a broker's token is not unique within its own
daily snapshot for seven of the ten brokers, so there is no reliable way to find that row again
later. `GET /api/instruments/additional_details` serves them.

The mapping runs as `bin/unified/map_instruments`, started by `unified-instruments.service` at 07:45 every
day after every broker's instrument download. It applies the mapping DDL, maps the day's broker
snapshots, caches the day's rows in Redis under `unified:` and warms the REST API's catalogue under
`unified:catalogue:`. See [Unified scripts](unified-scripts.md#instruments-map_instruments).

## Running it

```bash
bin/unified/map_instruments                          # every broker, today
bin/unified/map_instruments dhan kotak               # only these
bin/unified/map_instruments --date 2026-09-14        # a date already downloaded, not older than one already mapped
bin/unified/map_instruments --skip-collisions               # leave stale duplicate instruments alone
bin/unified/map_instruments --cache-only --date 2026-09-14   # only the contract sizes, Redis cache and catalogue, for a mapped date
```

A date older than the newest date already in `unified.broker_mappings` is refused. Mapping an older date on
top of newer data leaves seen dates and index names resolved in the wrong order, so a backfill has to start
from empty tables and run oldest date first.

!!! tip "A mapping fix is applied by re-running the mapping"

    This reads rows the download already stored, so unlike the download it can be re-run for a date
    still held. A download can only ever fetch today's file. So when a rules file turns out to be wrong,
    fix it and re-run the mapping - never re-download. Re-running today's date is allowed; an older date
    is refused while newer ones are mapped, as above.

    That is also why the mapping is a separate command from the downloads. The daily
    `unified-instruments.service` runs every `bin/<broker>/instruments` download and then
    `bin/unified/map_instruments` as separate steps of one unit.

## Identity is computed, not matched

The design decision that makes the rest of it simple: **there is no matching step.**

An instrument's identity is the composite natural key `(exchange, segment, shape, identity
fields)`, where the identity fields depend on the shape:

| Shape | Identity fields |
| --- | --- |
| `security` | `symbol` |
| `future` | `underlying_symbol`, `expiry_date` |
| `option` | `underlying_symbol`, `expiry_date`, `strike_price`, `option_type` |

Every adapter hashes that key to a UUID5 under one fixed namespace. Two brokers carrying the same
contract therefore compute the same `instrument_id` independently, without consulting each other or
any registry, and the upsert converges them onto one master row.

```python
instrument_id("nse", "nse_equities", "security", {"symbol": "RELIANCE"})
# '3f92570a-9924-5bf5-9f9d-e006cd9f4202', from every broker that lists it
```

ISIN and broker tokens are **classification aids only, never merge keys**. There is no fuzzy
matching anywhere in the identity path.

The three partial unique indexes on `unified.instruments`, one per shape, are that claim written as
a constraint: a second row claiming the same real instrument is rejected by the database rather
than merely unlikely.

!!! warning "`canonical_identity_value` is load-bearing"

    `str(Decimal('340'))` is `'340'` but `str(float('340'))` is `'340.0'` - two different hash
    inputs for one strike price, depending only on whether the value came from Postgres or a float
    cast. Every numeric is routed through `Decimal(...).normalize()` first for that reason.

    A change here does not raise. It silently splits one instrument into two master rows. The same
    goes for `IDENTITY_NAMESPACE`, and for the pandas version: pandas decides whether a null text
    column arrives as `None` or as `nan`, and `nan` stringifies to `"nan"` rather than falling to
    the empty-symbol path. Treat the pandas pin as part of the identity contract.

## Classification is declarative

Each broker has a rules file under
`stock_brokers/instruments/mapping/utilities/rules/`, listing its segments in canonical order:

```yaml
broker: dhan
raw_table: dhan.instruments
segments:
  - segment: nse_fixed_income
    exchange: nse
    shape: security
    rules:
      - match: {exch_id: NSE, segment: E, instrument_type: [DBT, DEB, TB, GB, CB, PTC]}
    identity:
      symbol: isin
    broker_fields:
      token: security_id
      broker_symbol: display_name
      lot_size: lot_size
      tick_size: {column: tick_size, transform: divide_by_100}
```

A `match` is satisfied when every named column equals the given value, or is one of a given list.
The first segment whose rules match wins. `identity` and `broker_fields` then map raw column names
onto the unified ones, optionally through a named transform from `TRANSFORMS` in `base.py` -
`divide_by_100`, `unix_epoch_date`, `kotak_expiry_epoch` and the rest.

`tick_size` is stored in rupees in every tradeable segment. Dhan, Kotak, Stoxkart and INDmoney publish
it in paise throughout their files, and Groww does for its commodity segments, so those segments carry
`divide_by_100`; Kotak's and Stoxkart's currency and rate derivatives are scaled by ten million instead.

Index tick sizes are in rupees too, although no index can be traded:

| Index segment | Kept as sent | Converted from paise | Dropped |
| --- | --- | --- | --- |
| `nse_equity_indices` | Dhan, Fyers | none | Stoxkart, whose tick is 1 on every row |
| `bse_equity_indices` | Dhan, Fyers | none | Stoxkart and Wisdom Capital, whose tick is 1 on every row |
| `mcx_commodity_indices` | Wisdom Capital | Kotak, Stoxkart | none |
| `ncdex_commodity_indices` | none | Stoxkart | none |

Stored prices back this up. NSE index prices are whole multiples of 0.05, which is Dhan's and Fyers' tick,
and most BSE index prices are not, matching their 0.01. A tick of zero or below, which Zerodha, Shoonya and
Kotak send for indices, is stored as null in every segment by `to_broker_fields` in `base.py`.

The uncategorised catch-alls are left as each broker sends them, because their rows mix units within one
broker. `lot_size` is never converted: it stays each broker's own figure, which on MCX means three
different things, as the [REST API guide](rest-api.md#instruments) describes.

Python is written only where equality rules cannot express a broker's quirks. Zerodha is the
extreme case: all 34 of its segments carry `rules: []` and it classifies entirely in code.

`_validate_config` rejects a rules file at load time whose segments are not canonical, whose shape
disagrees with its segment, whose segments are out of canonical order, or which lacks the final
`uncategorised` fallback.

## Nothing is dropped

A row matching no rule is not discarded. It lands in the catch-all for its exchange -
`nse_uncategorised`, `bse_uncategorised`, `mcx_uncategorised`, `ncdex_uncategorised`, or the
unprefixed `uncategorised` when even the exchange cannot be determined.

So `matched + uncategorised == raw_rows`, exactly, for every broker on every date. That identity is
the coverage check, and it makes a rules gap a visible number rather than a silent loss.

## Broker order is a correctness constraint

Brokers are mapped in the order given by `MAPPED_BROKERS`, not alphabetically and not in the
download subsystem's order:

```
dhan, kotak, groww, stoxkart, fyers, wisdom_capital, indmoney, flattrade, shoonya, zerodha
```

The reason is `equity_index_lookup` in `utilities/crossref.py`, which resolves a broker's index
names against the `nse_equity_indices` rows **already written for the same date**. Dhan and Kotak
publish a clean index vocabulary and so must go first; seven of the remaining eight read what they
wrote. Reordering or parallelising the loop produces alias-leaked index names and no error.

The other cross-broker aids in `crossref.py` pool the raw tables rather than master - which is why
mapping even a single broker needs every broker's raw snapshot present for that date.

## Duplicate merging

A full run ends with `utilities/collisions.py`, which merges away stale duplicates: a broker
publishing two rows for one scrip, where the other brokers agree on which name is live. Two
independent tests must both agree before anything is deleted, and only `broker_mappings` rows are
ever deleted - master rows are not.

A run in which fewer than all ten brokers had rows to map - a subset of brokers, or a day one download failed - skips this step, since one broker cannot vote on itself. `--skip-collisions` skips it too.

## Contract sizes

Straight after the mapping and the duplicate merge, `bin/unified/map_instruments` decides how many quotation units
one lot of every live currency and commodity derivative is, and writes each decision to `unified.contract_sizes`
for the date. The brokers' own `lot_size` figures cannot be compared on these markets, because each broker counts a
lot in its own unit: on MCX, GOLD's lot is 1 at Zerodha (one lot), 1 at Kotak (one kilogram) and 100 at Groww
(quotation units of 10 grams). Several brokers' instrument files also carry the exchange's contract size, and
[`contract_sizes.py`][stock_brokers.instruments.mapping.utilities.contract_sizes] reads those as independent
sources:

| Source | Read on | Figure |
| --- | --- | --- |
| Wisdom Capital | `MCXFO`, `NSECO` | `multiplier` |
| Kotak | `mcx_fo`, `nse_com`, `cde_fo` | `llotsize` × `lmultiplier` (when positive) × `dgennum` ÷ `dgenden` |
| Groww | `COMMODITY` | `lot_size` |
| Shoonya | `CDS` | `lotsize` × `multiplier` |
| Stoxkart | `NSECD`, `BSECD`, `NCDEX` | `lot_size` |

| Status | Meaning | Tradeable |
| --- | --- | --- |
| `confirmed` | At least two sources give a size, and every one gives the same | yes |
| `single_source` | Exactly one source gives a size | only on BSE currencies and NCDEX, where Stoxkart is the only broker listing them |
| `conflict` | The sources disagree | no |
| `no_source` | No source gives a size | no |

On 2026-09-15 every live MCX contract that any source covered was confirmed (15,887), as were 24,969 NSE commodity and
11,064 NSE currency contracts; 12 SILVER100 futures and 9 GBPINR and JPYINR options were conflicts, and BSE
currencies (13,089) and NCDEX (1,918) were single-source. The warm copies the decisions to Redis, and
`POST /api/orders/place` reads only them for a currency or commodity contract's lot size. To decide a date again:

```bash
python -m stock_brokers.instruments.mapping.utilities.contract_sizes --date 2026-09-15
```

## Checking a run

```bash
python -m stock_brokers.instruments.mapping.utilities.collisions --date 2026-09-12 --dry-run
```

`bin/unified/map_instruments` ends with a summary per broker - rows classified, uncategorised, instruments,
and any row errors - and exits 1 when a broker failed or rows could not be mapped. Convergence is what proves
the whole premise - a liquid instrument should carry a mapping from close to ten brokers under **one** id in
`unified.broker_mappings`. A count of one or two means brokers are computing different ids for the same
instrument.

## Asking it questions

`utilities/resolution.py` holds the lookups a consumer wants:

```python
from stock_brokers.instruments.mapping.utilities.resolution import MappingResolver

resolver = MappingResolver()
mapping_date, rows = resolver.broker_tokens(
    "nse", "nse_equities", "security", {"symbol": "RELIANCE"}, date.today())
```

Every method takes an `as_of_date` and uses the latest mapping on or before it, so a lookup for a
past date sees what was mapped then rather than what is mapped now.

## The three tier cache

Resolution sits in hot paths - a portfolio refresh resolves every holding, an order resolves an
instrument before it is placed - so a database round trip there is the thing to remove.
`utilities/cache.py` puts three tiers in front of the mapped tables, and the read order follows
what each one costs, measured on this machine:

| Tier | One call for 1000 tokens | One call per token |
| --- | ---: | ---: |
| This process's own memory | 0.18 µs | 1.1 µs |
| Redis, pipelined | 9.7 µs | 538 µs |
| Postgres | 29 µs | 1336 µs |

Each tier fills the ones above it on a miss. **Postgres remains the system of record** - nothing
here holds anything that cannot be rebuilt from it, so flushing Redis costs one query per
instrument actually touched and an unreachable Redis is a miss rather than an error.

Only the current mapping date is cached. A question about a past date goes straight to the queries
in `resolution.py` and caches nothing, because a backtest asking about March is not a hot path and
caching every historical date would multiply the memory for no benefit.

```bash
python -m stock_brokers.instruments.mapping.utilities.warm_cache --date 2026-09-12 --clear
```

The warm is the last step of every `bin/unified/map_instruments` run, and the keys are under
`unified:catalogue:`, the prefix named in `stock_brokers/instruments/mapping/utilities/tables.py`.

Warming is not required - the cache fills itself from Postgres as processes touch instruments -
but it means the first process of the morning is already fast. A full warm is about 3.1 million
fields, 40 seconds and 850 MB of Redis. The key naming the current date is written **last**, so a
reader sees either the previous complete day or the new complete day and never a half-written one.

!!! warning "Redis is built differently here than for the feeds"

    `MappingRedisConnection` does not use `get_cache()` from `utilities.configurations`. That client
    is built for long-lived connections: no `socket_timeout`, because a blocking stream read would otherwise
    raise on every idle period, and redis-py's default retry left in place. Both are right for a
    subscriber sitting silent overnight and wrong here, where a refused port takes about six seconds
    to be declared refused - and those six seconds land on whichever lookup happens to be first,
    which on this system is an order being placed. This client disables the retry and sets both
    timeouts, reaching the same conclusion in under a millisecond, and degrades to `None` rather
    than raising. The address still comes from `redis_configuration`, so there is one source of
    truth for where Redis is; only how this client waits on it differs.
