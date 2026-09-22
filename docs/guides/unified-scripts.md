# Unified scripts

The scripts in `bin/unified/` build one account-wide view out of what the
[broker scripts](broker-scripts.md) keep for each broker. They read **only Redis, MongoDB and the
database** - never a broker - so none of them logs in to a broker, places an order or spends a broker's
rate limit, and each one can be stopped, restarted or run by hand without disturbing a broker session.

They are grouped into folders by subject, the same way each broker's scripts are:

```text
bin/unified/
├── session/        connect, disconnect
├── user/           details, unified_details
├── brokers/        unified_details
├── exchanges/      unified_details
├── orders/         api_order_details, api_trade_details, websocket_order_details, store_orders_to_db
├── portfolio/      positions, holdings, funds, store_positions_to_db
└── instruments/    map, price_history, websocket_quotes, store_quotes_to_db
```

`unified_details` is the one name used more than once: three sibling scripts cache the three MongoDB
detail collections, one per folder, and the folder says which collection. Every other name is unique, so
it can be written on its own.

What they write is what the [REST API](rest-api.md) serves: the portfolio, order and detail routes read
the `unified:*` Redis keys, and the instrument, price and tick routes read the `unified` schema.

```bash
bin/unified/orders/api_order_details    # combine every broker's orders every half second
redis-cli GET unified:orders:orders
systemctl --user enable --now unified-orders@api_order_details.service
```

## The scripts

| Script | Runs | Reads | Writes |
| --- | --- | --- | --- |
| `map` | daily, once | `<broker>.instruments` | `unified.instruments`, `unified.broker_mappings`, `unified.contract_sizes`, the mapping cache |
| `price_history` | daily, once | `<broker>.price_history` | `unified.price_history` and its companion tables |
| `websocket_quotes` | continuously | `<broker>:quotes:stream` | `unified:quotes:live`, `unified:quotes:stream` |
| `websocket_order_details` | continuously | `<broker>:order-updates:stream`, `<broker>:positions_updates:stream` | `unified:order-updates`, `unified:positions_updates` and their streams |
| `api_order_details` | every 0.5 s | `<broker>:orders:orders` | `unified:orders:orders` |
| `api_trade_details` | every 0.5 s | `<broker>:orders:trades` | `unified:orders:trades` |
| `positions` | every 0.5 s | `<broker>:portfolio:positions` | `unified:portfolio:positions` |
| `funds` | every 0.5 s | `<broker>:portfolio:funds` | `unified:portfolio:funds` |
| `holdings` | every 60 s | `<broker>:portfolio:holdings` | `unified:portfolio:holdings` |
| `details` | every 60 s | `<broker>:user:details` | `unified:user:details` |
| `user/unified_details` | every 60 s | MongoDB `user_details` | `unified:details:users` |
| `brokers/unified_details` | every 60 s | MongoDB `broker_details` | `unified:details:brokers` |
| `exchanges/unified_details` | every 60 s | MongoDB `exchange_details` | `unified:details:exchanges` |
| `connect`, `disconnect` | by hand | MongoDB `settings` | the application's token, `unified:session:status` |
| `store_quotes_to_db` | continuously | `unified:quotes:stream` | `unified.ticks` |
| `store_orders_to_db` | continuously | `unified:order-updates:stream` | `unified.order_updates` |
| `store_positions_to_db` | continuously | `unified:positions_updates:stream` | `unified.positions` |

The combiners resolve each broker's token to a unified instrument through the mapping cache
(`unified:broker_tokens`, and `unified:instrument_symbols` for Groww, which sends no token), and price
holdings and positions from `unified:quotes:live`. Until `map` has written that cache nothing
resolves, and every order, trade and position carries a null `instrument_id`.

## The portfolio and order documents

`api_order_details`, `api_trade_details`, `positions`, `holdings` and `funds` each write one JSON document
with SET, in the shape
the matching REST route answers:

| Key | Document |
| --- | --- |
| `unified:orders:orders` | `{"orders": [...], "summary": {"count", "by_status", "filled_value"}, "brokers": [...], "as_of"}` |
| `unified:orders:trades` | `{"trades": [...], "summary": {"count", "buy_value", "sell_value", "total_value"}, "brokers": [...], "as_of"}` |
| `unified:portfolio:positions` | `{"net": [...], "day": [...], "summary": {"net", "day"}, "brokers": [...], "as_of"}` |
| `unified:portfolio:holdings` | `{"holdings": [...], "summary": {"holdings_count", "total_investment", "total_current_value", "total_unrealized_pnl"}, "brokers": [...], "as_of"}` |
| `unified:portfolio:funds` | `{"summary", "pnl", "margin_breakdown", "cash_movement", "segments", "brokers": [...], "as_of"}` |

Orders and trades are listed per broker and not merged, sorted by broker, then time, then id. Holdings
are merged into one row when two brokers share an ISIN or an instrument id; positions when they share an
instrument and a product. `day` positions come only from Zerodha and Wisdom Capital, the two brokers that
report a day view. Funds are summed across brokers, with `total_balance` taken as `available_balance`
plus `margin_utilized`, since no broker reports a total. Each script's docstring has the per-broker
field table it reads with.

### The `brokers` list

Every document carries `brokers`, one entry per broker saying how its stored data was read:

```json
{"broker": "zerodha", "status": "ok", "as_of": "2026-09-14 10:02:11.402913"}
```

| Status | Meaning | Included |
| --- | --- | --- |
| `ok` | Stored recently | yes |
| `stale` | Stored longer ago than the threshold - its script has probably stopped | yes |
| `missing` | No key: the broker's scripts have not run today | no |
| `unreadable` | A stored value that is not the expected shape, such as a refusal carried in a successful answer. Funds add an `error` saying why | no |

The threshold is a minute for orders, trades, positions and funds, and three minutes for holdings. For
orders and positions `as_of` is the newer of the newest entry's `observed_at` and the broker poller's
`<broker>:orders:orders:polled_at` or `<broker>:portfolio:positions:polled_at`, so a day with no orders,
or a flat account, is still `ok` while the poller runs. A missing or unreadable broker contributes nothing,
so it is never mistaken for a broker holding no money or no positions.

## Instruments: `map`

```bash
bin/unified/instruments/map                      # every broker, today
bin/unified/instruments/map dhan kotak           # only these
bin/unified/instruments/map --date 2026-09-14    # a date already downloaded, not older than one already mapped
bin/unified/instruments/map --skip-collisions    # leave stale duplicate instruments alone
bin/unified/instruments/map --cache-only --date 2026-09-13   # only rewrite the Redis cache for a mapped date
```

Each run applies the mapping DDL, maps the date's broker snapshots with the [instrument mapping](instrument-mapping.md) stage, decides the date's currency and commodity [contract sizes](instrument-mapping.md#contract-sizes) into `unified.contract_sizes`, and then writes the cache and warms the REST API's catalogue.
`--cache-only` skips the DDL and the mapping, and only decides the contract sizes, writes the cache and warms the catalogue.
A contract size decision that fails is logged without failing the run.
A date older than the newest date already in `unified.broker_mappings` is refused with exit 2: a backfill
has to start from empty tables instead.

| Key | Type | Holds |
| --- | --- | --- |
| `unified:instruments` | hash | Every instrument mapped on the date, keyed by `instrument_id`, each a JSON array of `exchange`, `segment`, `shape`, `symbol`, `underlying_symbol`, `expiry_date`, `strike_price`, `option_type`, `first_seen_date`, `last_seen_date` |
| `unified:broker_mappings` | hash | Keyed `broker:instrument_id`, each a JSON array of `broker_token`, `broker_symbol`, `order_symbol`, `lot_size`, `tick_size` |
| `unified:broker_tokens` | hash | The reverse lookup, keyed `broker:broker_token`, each a JSON array of the instrument ids that token names on the date |
| `unified:instrument_symbols` | hash | Securities by symbol, keyed `segment:SYMBOL` (`nse_equities:RELIANCE`), each an instrument id as a JSON string |
| `unified:mapping:meta` | string | `mapping_date`, the four counts, `columns` and `written_at` |
| `unified:catalogue:*` | various | The REST API's instrument cache - identities, tokens, order handles, contract size decisions, each broker's additional instrument attributes and a browsable catalogue per segment - warmed for the date |

The four hashes are built under `:staging` keys and swapped in together with the meta, so a reader sees
the previous day's complete cache or the new one, never a mix. The catalogue warm clears every other
date's `unified:catalogue:` keys; a warm that fails is logged without failing the run, and the API reads
the unified tables until the next warm succeeds.

## Price history: `price_history`

```bash
bin/unified/instruments/price_history daily                  # load, corrections, load, factors, verify
bin/unified/instruments/price_history load --symbols RELIANCE,NIFTY
bin/unified/instruments/price_history factors --stale-days 14
bin/unified/instruments/price_history status
redis-cli GET unified:prices:last_run
```

The steps, the options and the rules they follow are described in
[Unified price history](unified-price-history.md). `daily` is the scheduled sequence; a failing `verify` inside it is reported without
failing the job. Every run first applies the mapping and price DDL and `unified.ticks` with its adjusted
view, and each run's outcome is written to `unified:prices:last_run`.

## Live quotes: `websocket_quotes`

`websocket_quotes` reads all ten broker quote streams as the consumer group `unified` - apart from the `persist`
group, so each gets every tick - and turns them into one [unified quote](../architecture/contracts.md#the-unified-quote)
per instrument. Each tick goes through six steps, cheapest refusal first:

1. **Resolve** its token to an instrument, once per token per mapping date, through `unified:broker_tokens`
   among the segments the token's exchange and kind allow. Fyers' symbol is first turned into its token
   through the order symbols in `unified:broker_mappings`. An expired contract is ruled out, and a token that
   still names more than one instrument is not guessed at.
2. **Session:** a tick received outside its instrument's window is dropped, which keeps weekend replays and
   mock sessions out.
3. **Ownership:** one broker owns an instrument at a time, and only its ticks are written.
4. **Normalize** the values, as the contract describes.
5. **Previous close** is carried from an earlier owner's tick the same India day when the owner does not
   send it, and the change is recomputed from it.
6. **De-duplicate:** a tick that changes nothing but the clock is dropped.

| Key | Holds |
| --- | --- |
| `unified:quotes:live` | Hash keyed by `instrument_id`: the unified quote document, quantities in units, times in epoch seconds, with `stale` and `stale_since` when the owner went silent without a healthy backup |
| `unified:quotes:stream` | Every quote written, as field `quote`, capped at about 1,000,000 entries |
| `unified:quotes:stats` | Counts of received, unresolved, out_of_session, not_owner, no_price, duplicate and written ticks |
| `unified:quotes:unresolved` | Counts per unresolved `broker:token:reason` |

The group is created at the end of each stream the first time, since a live cache has no use for history.
Only instruments some broker's `websocket_quotes` script is subscribed to are in the hash; an instrument nobody streams
is simply absent. A quote stale for a week is removed, and today's previous closes are recovered from the
hash at start.

There is no instrument list here to keep in step with the brokers': this script writes a quote for whatever
arrives on the ten streams, so its coverage is exactly the coverage of the feeds. Since `bin/zerodha/instruments/websocket_quotes`
began carrying Zerodha's whole instrument master on 2026-09-16, that is close to every instrument Zerodha
lists. Running the resolver's own rules over that day's master, 112,422 of the 112,657 instruments resolve to
exactly one unified instrument and 235 do not, so `unified:quotes:live` should hold about 112,400 instruments
rather than the sixteen it held before. At a measured 823 bytes per quote document that hash is roughly 92 MB.

The 235 that do not resolve fall into three groups.
Every one of them logs a warning the first time it is seen under a mapping date, and is tried again every ten minutes, each failed attempt counted in `unified:quotes:unresolved`:

| Why it fails | Count | Which instruments |
| --- | ---: | --- |
| `ambiguous` - the token names more than one unified instrument, which is never guessed at | 170 | BSE |
| `unmapped` - the token's segment code allows segments the instrument was not filed under | 64 | 28 NCO securities filed as `nse_commodities` rather than a derivative segment, 12 GLOBAL and 1 NSEIX index filed as `uncategorised` on exchange `unknown`, 11 MCX and 12 NSE indices filed outside the index segments |
| `unmapped` - no entry in `unified:broker_tokens` at all | 1 | NSE:ELECTCAST |

!!! warning "The unified feed has not been run at this size"

    `bin/unified/instruments/websocket_quotes` is one process reading all ten streams 500 entries at a time, and it had 4.6 million
    ticks through it when the feeds carried fifteen instruments each. Whether it keeps up with Zerodha's whole
    master has not been measured. Its hourly stale purge also reads and parses every field of
    `unified:quotes:live` on the same thread that processes ticks, which is a scan of about 112,400 documents
    rather than sixteen. Watch `unified:quotes:stats` and the `unified` group's lag on
    `zerodha:quotes:stream` after a restart.

### One broker per instrument

Brokers are never blended. At any moment one broker owns an instrument and only its ticks are written;
another broker streaming the same instrument is a standby.

- Priority is Zerodha, Dhan, Kotak, Flattrade, Shoonya, Fyers, Wisdom Capital, Groww, INDmoney, Stoxkart -
  without INDmoney on MCX, and only Shoonya and Wisdom Capital on NCDEX - with verified brokers ahead of
  unverified ones. Zerodha is the only verified broker. Stoxkart is last; its feed is the undocumented
  broadcast websocket of Stoxkart's trading website, which Stoxkart may change without notice.
- A new instrument goes at once to the top verified broker; any other waits 5 seconds for a better one.
- The owner loses it when its stream has been silent for 45 seconds, or when it has sent nothing for that
  instrument for 60 seconds while a standby sent it 3 times. The best healthy standby takes over.
- A higher-ranked verified broker takes an instrument back once its stream has been continuously healthy
  for 60 seconds, so a flapping connection cannot pull ownership to and fro.
- Ownership starts afresh at each session's end.

Health is judged per broker stream from the ticks it carries, since the streams carry no heartbeats. When
no broker is healthy the cached quote is kept, with `stale` set and `stale_since` saying when; the owner's
next tick clears it. No ownership history is recorded. The REST API's broker quotes use the same priority
order, from `stock_brokers/instruments/ticks/utilities/sources.py`.

### The trading calendar

Which days trade is taken from the exchanges' own calendars, kept one file a year in
`stock_brokers/instruments/ticks/utilities/calendars/`, generated from each exchange's publication -
NSE's holiday API, BSE's and MCX's holiday pages, and NCDEX's circular - with the sources cited at the
top of the file. They are kept per exchange and per calendar, because one exchange's segments do not
close together:

| Calendar | Segments | Window, India time | Closures |
| --- | --- | --- | --- |
| `equity` | cash, indices, equity derivatives | 09:00-16:00 | whole day |
| `currency` | currency derivatives | 09:00-17:30 | whole day, including bank holidays the equity segment trades through |
| `commodity` | MCX, and NSE and BSE commodity derivatives | 09:00-23:59, split at 17:00 | whole day, or only the morning or only the evening |
| `commodity` on NCDEX | NCDEX | 09:00-21:30, split at 17:00 | as above |

On most equity holidays the commodity evening session still trades - Ganesh Chaturthi, 2026-09-14,
closes the equity and currency segments and NCDEX all day, but MCX only until 17:00. A day whose
evening is closed keeps its window open until 17:30 for the morning's closing prices. Special sessions
open a window on a closed day: Muhurat trading on Sunday 2026-11-08 accepts the whole day until the
exchanges notify its hours, when `opens` and `closes` in the file should be narrowed.

A date the calendar does not list is a trading day. The exchanges publish the next year's calendars
each December and revise them by circular during the year; add or amend the year's file then, and run
`python -m test_runs.unified_ticks_sessions`, which checks the file against dates the publications
state. The REST API's quote service reads the same files; its exchange details serve the copy
`import-api-details --calendars-only` writes to MongoDB, which has to be run again after a file changes.

### What each broker's values mean

Every normalizer rests on facts about its broker. Only Zerodha is verified; the others supply an instrument
only when no verified broker streams it, until a live session confirms what is marked unconfirmed below.

| Broker | Previous close | MCX quantities | Timestamps | Evidence so far |
| --- | --- | --- | --- | --- |
| Zerodha | `close`, always | lots | both true instants | In-session MCX ticks, 2026-09-11 |
| Dhan | `close` before the session ends; also the previous close packet | lots | trade time only | In-session MCX ticks agree with Zerodha on every field |
| Flattrade, Shoonya | `c` before the session ends | lots (open interest confirmed) | `ft`; `ltt` parsed since 2026-09-13 | Weekend snapshots and Saturday's mock session |
| Kotak | `close`, always | every quantity is lots times Kotak's own lot size | both true instants | In-session HSM ticks, 2026-09-15, agree with Zerodha on price, close, times and, after lot scaling, every NSE and MCX quantity |
| Wisdom Capital | not used - XTS `Close` is the last price | lots (unconfirmed) | both true instants | Mock session agrees with Flattrade on price, volume and time |
| Fyers | `prev_close_price`, always | lots (unconfirmed) | both | Protocol only; nothing stored yet. Currency derivatives left out |
| Groww | not used until confirmed | NSE and BSE only | exchange time | Protocol only; nothing stored yet |
| INDmoney | not used - `close` is the last price | NSE and BSE only | both true instants | In-session NSE ticks, 2026-09-15, agree with Zerodha on price, volume and times; no order book quantities |
| Stoxkart | `close` before the session ends, from the previous close packet | lots | both true instants on NSE, counted from 1980 and converted by `bin/stoxkart/instruments/websocket_quotes`; no exchange time on MCX | Streamed broadcast ticks, 2026-09-15, agree with Zerodha at the same moment on last price, volume, average price, OHLC and previous close (TCS, RELIANCE, HDFCBANK, CRUDEOIL SEP), total bid and offered quantity and first depth level (RELIANCE, HDFCBANK, CRUDEOIL), MCX open interest in lots (15634), last trade time and NSE exchange time |

Where a broker's `close` is not used, the previous close carries forward from whichever broker owned
the instrument earlier that day, and is null if none did. `bin/unified/instruments/websocket_quotes` carries these normalizers
itself, in `build_normalizers`; the same facts are stated for the REST API's broker quotes in
`stock_brokers/instruments/ticks/<broker>.py`.

## Order and position updates: `websocket_order_details`

`websocket_order_details` reads the order update streams of all ten brokers and the four position update streams
(Fyers, Groww, Kotak, Wisdom Capital), fourteen streams in all, as the group `unified`. Stoxkart streams
no position updates. An order update is normalized as the broker's own script normalizes it, except that
Stoxkart's entry already carries the normalized `order` its script built, which is used as it is. The
order is then given `broker`, `instrument_id` and `observed_at`; a position update is built into the REST
position contract as `positions` builds one, with `broker`, `position_key`, `basis` and
`observed_at`. Neither is merged with anything else.

| Key | Type | Holds |
| --- | --- | --- |
| `unified:order-updates:stream` | stream | Every order update, field `update`, capped at about 50,000 |
| `unified:order-updates` | hash | The latest update per order, keyed `broker:order_id` |
| `unified:positions_updates:stream` | stream | Every position update, field `position`, capped at about 50,000 |
| `unified:positions_updates` | hash | The latest update per position, keyed `broker:position_key` |

The hashes expire at 06:00 IST like the brokers' merged hashes, and an update observed before the latest
06:00 goes to the stream but not the hash, so yesterday's orders do not refill today's.

## Profiles, details and the session

`details` writes `unified:user:details`, one object with a key for each of the ten brokers and that
broker's profile `data` as the value, or `null` when its key is missing or holds no profile. Stoxkart's
`email_id` arrives encrypted, as `ENC-` followed by hexadecimal, so it is not a readable address. Kotak's comes
from `bin/kotak/session/connect` and Wisdom Capital's is refreshed once a day, so each is as fresh as its own
script keeps it.

Three sibling scripts named `unified_details` copy the MongoDB detail collections into Redis every minute,
each a JSON array of the collection's documents without `_id`. MongoDB stays the store of record, and
`--once` copies and exits.

| Script | Collection | Key | Served by |
| --- | --- | --- | --- |
| `bin/unified/user/unified_details` | `user_details` | `unified:details:users` | `GET /api/users/details` |
| `bin/unified/brokers/unified_details` | `broker_details` | `unified:details:brokers` | `GET /api/brokers/details` |
| `bin/unified/exchanges/unified_details` | `exchange_details` | `unified:details:exchanges` | `GET /api/exchanges/details` |

One script used to cache all three keys in a single MULTI, so a reader never saw a new
`unified:details:exchanges` beside an old `unified:details:brokers`. Three processes cannot do that, so a
reader can now find one key updated while another still holds the copy from the minute before. Nothing
depends on the three changing together: they describe different things, and no route reads more than one
of them.

`connect` and `disconnect` are the command-line equivalents of the REST API's connect and disconnect, taking the
api key from `--api-key` or `UNIFIED_BROKER_INTERFACE_API_KEY` and the secret from
`UNIFIED_BROKER_INTERFACE_API_SECRET` or a prompt - never from an argument. `connect` issues the one
application-wide token and writes
`{"status": "success", "access-token": …, "last_login": …, "expires_at": …}` to `unified:session:status`;
`disconnect` revokes the token for every client and writes `"status": "logged out"` with the token,
`last_login` and `expires_at` null. Unlike a
broker's logout, this one does end the session, since the token is this application's own.

## Persisters

`store_quotes_to_db`, `store_orders_to_db` and `store_positions_to_db` read their stream as the group `persist` and COPY
a batch at a time, acknowledging an entry only after its batch is committed - so nothing is lost across a
restart, and a batch committed just before a crash can be written twice. Each creates its table on start
from its `.sql` file. Run one instance of each.

| Script | Table | One row per |
| --- | --- | --- |
| `store_quotes_to_db` | `unified.ticks` | Accepted quote; stale quotes and those without an instrument are skipped |
| `store_orders_to_db` | `unified.order_updates` | Transition of an order |
| `store_positions_to_db` | `unified.positions` | Snapshot of a position |

## The unified schema

| Object | Kind | Written by |
| --- | --- | --- |
| `unified.instruments` | table | `map` |
| `unified.broker_mappings` | hypertable by `mapping_date` | `map` |
| `unified.contract_sizes` | hypertable by `mapping_date` | `map` |
| `unified.price_history`, `unified.price_history_sources`, `unified.price_history_corrections`, `unified.adjustment_factors`, `unified.yahoo_fetch_state` | tables | `price_history` |
| `unified.adjustment_ranges`, `unified.correction_ranges`, `unified.price_history_adjusted` | views | - |
| `unified.adjusted_bars` | function | - |
| `unified.ticks` | hypertable, compressed after 7 days | `store_quotes_to_db` |
| `unified.ticks_adjusted` | view | - |
| `unified.order_updates` | hypertable | `store_orders_to_db` |
| `unified.positions` | hypertable | `store_positions_to_db` |

The DDL lives in numbered `.sql` files, every statement safe to re-run, applied in filename order by the
scripts that need them (see [DDL and migrations](../database/ddl.md)):

| Directory | Files |
| --- | --- |
| `stock_brokers/instruments/mapping/utilities/sql/ddl` | `100_unified_schema.sql`, `110_unified_instruments.sql`, `120_unified_broker_mappings.sql`, `130_unified_contract_sizes.sql` |
| `stock_brokers/instruments/historical/utilities/sql/ddl` | `200_unified_price_history.sql` to `250_unified_price_history_corrections.sql` |
| `stock_brokers/instruments/ticks/utilities/sql/ddl` | `300_unified_ticks.sql`, `310_unified_order_updates.sql`, `320_unified_positions.sql`, `330_unified_ticks_adjusted.sql` |

`330` reads `unified.adjustment_ranges` from the price DDL, so it is applied by `price_history`, not by
`store_quotes_to_db`.

### Table names

The mapping and price history packages name their tables in two modules rather than in each query:
`stock_brokers/instruments/mapping/utilities/tables.py` - `unified.instruments`, `unified.broker_mappings`,
`unified.contract_sizes` and the catalogue's Redis prefix, `unified:catalogue:` - and
`stock_brokers/instruments/historical/utilities/unified/tables.py` - the price history tables, views and
function, and `unified.ticks` and `unified.ticks_adjusted`. Both name only the `unified` schema.

## Running them under systemd

The units live in `services/unified/`:

| Unit | Type | What it does |
| --- | --- | --- |
| `unified-instruments@.service`, `unified-orders@.service`, `unified-portfolio@.service`, `unified-user@.service`, `unified-brokers@.service`, `unified-exchanges@.service` | templates | One per folder, running one long-lived script from it: `unified-instruments@websocket_quotes` runs `bin/unified/instruments/websocket_quotes`. Restarted 15 s after exiting, except on exit 2 |
| `unified-mapping.service` | oneshot | Every broker's `daily_feed`, Stoxkart's included, then `map`. A failed download does not stop the others or the mapping; the mapping's exit status is the unit's |
| `unified-mapping.timer` | timer | 07:45 IST every day, `Persistent=true` - a missed snapshot can never be fetched later |
| `unified-prices.service` | oneshot | `price_history daily`, ordered after `unified-mapping.service` |
| `unified-prices.timer` | timer | 08:30 IST Monday to Saturday, `Persistent=true` |
| `unified-rest-api.service` | service | `bin/rest-api`; a route whose key is missing answers 503 rather than the service failing to start |
| `unified.target` | target | Everything above |

`connect` and `disconnect` have no units. Install from the comments in `unified.target`:

```bash
systemctl --user link ~/Projects/unified_broker_interface/services/unified/*
systemctl --user daemon-reload
systemctl --user enable --now unified.target unified-mapping.timer unified-prices.timer \
    unified-instruments@websocket_quotes.service unified-instruments@store_quotes_to_db.service \
    unified-orders@api_order_details.service unified-orders@api_trade_details.service \
    unified-orders@websocket_order_details.service unified-orders@store_orders_to_db.service \
    unified-portfolio@positions.service unified-portfolio@holdings.service \
    unified-portfolio@funds.service unified-portfolio@store_positions_to_db.service \
    unified-user@details.service unified-user@unified_details.service \
    unified-brokers@unified_details.service unified-exchanges@unified_details.service \
    unified-rest-api.service
```

The unified scripts only have data to combine while each broker's target is running.

## The daily timeline

| IST | What happens |
| --- | --- |
| 06:00 | The brokers' merged order and position hashes and the unified update hashes reset |
| 07:00-07:30 daily | Each `<broker>-login.timer` fires at 07:00 plus up to 30 minutes of random delay |
| 07:45 daily | `unified-mapping`: ten instrument downloads, then `map` and the cache warm - about three quarters of an hour |
| 08:30 Mon-Sat | `unified-prices`: `price_history daily`; on Saturday it picks up Friday's last bars and the week's corporate actions. When the 07:45 job is still running, it waits for that to finish first |
| 09:00 | Pre-open. The feeds resolve against the day's mapping |

Everything else runs continuously: the pollers, feeds, combiners, persisters and each broker's
`price_history` worker.

## Looking at it

```bash
systemctl --user list-timers 'unified*'
journalctl --user -u unified-mapping --since today
journalctl --user -u unified-orders@api_order_details -f
redis-cli GET unified:mapping:meta
redis-cli GET unified:orders:orders | jq '.brokers'
redis-cli XINFO GROUPS unified:quotes:stream
```
