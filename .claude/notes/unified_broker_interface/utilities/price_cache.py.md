# Notes on `unified_broker_interface/utilities/price_cache.py`

## Why the cache exists, and what the user chose

On 2026-09-22 the user asked for `/api/instruments/prices` to keep a copy of every answer in Redis and to serve a later request for the same instrument from that copy rather than querying TimescaleDB again. Three decisions were put to them, and they chose:

- **Slice a wider cached window**, not exact-range keys. One entry per series holds the widest range read so far, and any request whose range falls inside it is sliced out. The alternative, putting `from` and `to` into the key, was rejected because a caller asking for a year and then for a month inside it would query twice.
- **The loader stamp plus a TTL**, not a fixed TTL alone and not clearing by hand from `bin/unified/historical_prices`. The stamp keeps the loader's own code untouched and the correctness rule visible in the API.
- **Every interval, with a size cap**, not daily only. Intraday charts get the benefit, and the cap stops one instrument taking eleven megabytes.

## The stamp is what makes a cached copy safe

`unified.adjusted_bars` exists so that adjustment happens on read: the DDL's own comment says correcting a factor corrects every query at once and nothing has to be rewritten. A Redis copy of adjusted candles is the first thing in this project that can hold prices the database has since revised, so the copy has to be able to tell that it is out of date.

`bin/unified/historical_prices` already writes the outcome of every run to `unified:prices:last_run`, so the `finished` time in that JSON is used as the stamp. A copy records the stamp in force when it was built, and `load()` throws the copy away when the stamp has changed. A load, a correction or a rebuilt factor therefore drops every copy without the loader knowing this cache exists.

Two consequences are deliberate rather than accidental:

- The script writes `last_run` on *every* invocation, including the read-only `status` and `sources` steps, so running `bin/unified/historical_prices status` drops the whole cache. That costs one query per series afterwards and nothing else, which is a much better trade than teaching this module which steps change data.
- `replace()` stamps the copy with the value read in `load()`, *before* the query ran, not with a fresh read afterwards. If a load finishes while the query is in flight, the rows may be a mix of before and after, and the pre-query stamp makes the next request discard that copy. Stamping it afterwards would have left a mixed copy claiming to be current for a whole day.

When `last_run` cannot be parsed at all, `loader_stamp` returns `None` and the cache turns itself off for that request rather than guessing. When the key is simply unset, because the loader has never run on this machine, the stamp is the constant `"none"` and caching works normally.

## Why the union is read in one query

A request reaching outside the stored window could be answered by reading only the missing days and merging them into the copy. Reading the union of the two ranges instead is one query rather than two, needs no merge, and leaves one entry behind rather than two that overlap. The cost is re-reading days already held, which on a compressed hypertable segmented by instrument and interval is cheap next to a second round trip.

The union is refused when it would span more days than the interval allows a caller to ask for. Without that guard a stored year of one minute bars plus a request for the following week would turn a legal request into a query well past `MAX_INTRADAY_DAYS`, which the endpoint would never accept from a caller directly. The limit is passed in from `instrument_history.candles()` rather than imported, because `instrument_history` imports this module and the limit is a rule about requests, not about caching.

## Why the boundaries are found by binary search

Slicing needs the index of the first candle at or after an instant. The stored timestamps are ISO strings, and their offset depends on the PostgreSQL session's time zone, so comparing the strings lexicographically against a boundary string would be wrong the moment the two offsets differ. Parsing every timestamp is correct but costs about 137,000 `fromisoformat` calls for a year of one minute bars. The binary search in `_first_at_or_after` parses about a dozen of them and is correct whatever the offset, because it compares aware datetimes.

The remaining per-request cost is `json.loads` over the whole entry, up to a few tens of milliseconds for an entry at the cap. That is still far less than the query it replaces, and it is the reason the cap exists at all.

## Odds and ends

`len(entry)` counts characters rather than bytes when the size is checked. Every character an entry can hold is ASCII - ISO timestamps, numbers, the fixed column names and the key's own punctuation - so the two counts are equal, and encoding the string only to measure it would double the memory used at the moment the entry is largest.

The stored `columns` are compared with the columns the answer now carries, and a mismatch drops the copy. Nothing in the current code changes that list, but a deploy that added a column would otherwise serve old-shaped rows for up to a day, which is a bug worth two lines to rule out.

An oversized answer leaves any narrower copy in place instead of deleting it. The narrower copy is still correct for the range it covers, so keeping it is strictly better than having nothing.

## What is not covered

There is no way to ask the endpoint to bypass the cache, which would be a `fresh=true` parameter if it is ever wanted. The key space is bounded only by the day's expiry and by traffic: every instrument, interval, basis and `known_as_of` a caller asks for gets its own entry, each up to two megabytes.
