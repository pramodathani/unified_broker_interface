# Redis keys

Every key the running scripts write is namespaced. `<broker>:` keys are written by that broker's
[scripts](../guides/broker-scripts.md) in `bin/<broker>/`, and `unified:` keys by the
[unified scripts](../guides/unified-scripts.md) in `bin/unified/` and by the [REST API](../guides/rest-api.md).
The second part of a name says what the key is about - `session`, `user`, `orders`, `portfolio`,
`quotes`, `instruments` - so `zerodha:portfolio:funds` and `unified:portfolio:funds` hold the same thing
for one broker and for every broker together.

The keys come in three kinds:

- a **string** holding one JSON document, replaced whole with `SET` by each poll or run;
- a **hash** of JSON values, one field per order, position, quote or instrument;
- a **Redis Stream** holding every message in arrival order, trimmed to an approximate cap and read
  through consumer groups. The persisters read as the group `persist` and the unified scripts as the
  group `unified`, so each gets every entry and neither disturbs the other. An entry is acknowledged
  only after it has been written, so a restart resumes from the pending entries.

## Per broker

`<broker>` is one of `dhan`, `flattrade`, `fyers`, `groww`, `indmoney`, `kotak`, `shoonya`, `stoxkart`,
`wisdom_capital` and `zerodha`.

### Session and profile

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:session:status` | string | `bin/<broker>/session/connect`, `disconnect` | `{"status", "access-token", "last_login"}`, replaced on every run. Wisdom Capital's also carries `market-data-access-token` |
| `<broker>:user:details` | string | `bin/<broker>/user/details`, and `KotakAPI` for Kotak | `{"timestamp", "status", "code", "data"}`, the broker's profile under `data` |

`status` is `success`, `failure` or `logged out`. On success `last_login` is when the token in force was
issued, which is earlier than the run when the stored session was still good; on failure it is when the
attempt was made; after a logout both it and `access-token` are null. A broker logout only marks this
key - nothing is sent to the broker, because its logout endpoint would invalidate the one token every
other process is using.

The profile is polled every minute. Wisdom Capital's is fetched once a day, since it allows about one
profile call a day. Kotak has no profile endpoint at all: its profile arrives only in the Login Validate
response, so `KotakAPI` writes `kotak:user:details` itself every time it logs in. Any process can therefore
be the one that refreshes it, which is the point - Kotak's token expires at midnight, the running pollers
re-login the moment it does, and `bin/kotak/session/connect` finds a healthy session hours later when its
07:00 timer fires.

Wisdom Capital needs two sessions, because Symphony XTS splits a broker into an interactive application
and a market data one with separate credentials. Both tokens live in the `last_login` hash, as
`access_token` and `market_data_access_token`, and both are established by constructing
`WisdomCapitalAPI`. `wisdom_capital:session:marketdata:lock` is held while one process replaces a refused
market data token, because XTS issues exactly one market data session per application key and a second
login invalidates the first.

### Orders

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:orders:orders` | hash, keyed by the broker's order id | `bin/<broker>/orders/api_order_details` and `bin/<broker>/orders/websocket_order_details` | `{"observed_at", "source", "order", "data"}` per order |
| `<broker>:orders:orders:polled_at` | string | `bin/<broker>/orders/api_order_details` | When the order book was last read successfully, epoch seconds |
| `<broker>:orders:trades` | string | `bin/<broker>/orders/api_trade_details` | `{"timestamp", "status", "code", "data"}`, the day's trade book under `data` |
| `<broker>:order-updates:stream` | stream, field `update` | `bin/<broker>/orders/websocket_order_details` | Every order update as `{"timestamp", "data"}`, with the normalized `order` added at Stoxkart, capped at about 20,000 |

`orders:orders` is the one hash for a broker's orders, merged from two writers. `source` is `rest` or
`websocket`, `order` is the order normalized onto the shared vocabulary - status `PENDING`, `OPEN`,
`COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED` - and `data` is the broker's own order exactly as sent.
A websocket update always replaces its order's entry; a polled row replaces it only when the entry was
observed before the poll's request was sent, so an update that arrived while the request was in flight
is never overwritten by the older snapshot. The check and the write run together as one Redis script.

Stoxkart's entries also carry a top-level `variety` beside `data`, such as `NORMAL`, `AMO` or `BO`, which
`PUT /api/orders/modify` and `DELETE /api/orders/cancel` build Stoxkart's modify and cancel URLs from. It is stored apart from `data` because
Stoxkart's order socket reports `NORMAL` for an after-market order, so `bin/stoxkart/orders/websocket_order_details` keeps
an `AMO` or `BO` variety already stored rather than taking the socket's.

`polled_at` exists because Redis keeps no empty hash, so the hash alone cannot say that an empty book
was read. Both keys expire at 06:00 IST, and every write moves that to the next 06:00, so yesterday's
orders stay readable overnight and the first poll of the day starts afresh.

The stream is written by the `websocket_order_details` scripts of all ten brokers. It is read by
`bin/<broker>/orders/store_orders_to_db` into `<broker>.order_updates`, and by `bin/unified/orders/websocket_order_details`.
Flattrade's `websocket_order_details` script exists but is not run, since Flattrade permits one websocket per
session and its quotes script holds it.

### Portfolio

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:portfolio:positions` | hash, keyed per position | `bin/<broker>/portfolio/positions`, and `websocket_order_details` where the broker streams positions | `{"observed_at", "source", "position", "data"}` per position |
| `<broker>:portfolio:positions:polled_at` | string | `bin/<broker>/portfolio/positions` | When the positions were last read successfully, epoch seconds |
| `<broker>:positions_updates:stream` | stream, field `position` | `bin/<broker>/orders/websocket_order_details` | Every position update as `{"timestamp", "data"}`, capped at about 20,000 |
| `<broker>:portfolio:holdings` | string | `bin/<broker>/portfolio/holdings` | `{"timestamp", "status", "code", "data"}`, polled every minute |
| `<broker>:portfolio:funds` | string | `bin/<broker>/portfolio/funds` | `{"timestamp", "status", "code", "data"}` |

The positions hash follows the orders hash exactly - the same merge rule, the same `polled_at`, the same
06:00 IST expiry. Its field names a position the way the broker holds one, such as Zerodha's
`NET:exchange:instrument_token:product` and `DAY:...`, Kotak's `exSeg:tok:prod` or Fyers'
`symbol:product` and Stoxkart's `exchange:token:product_type`, so a position lands on one field whichever
script wrote it.

Only Fyers, Groww, Kotak and Wisdom Capital stream positions, so only they have a
`positions_updates:stream`, read by `bin/<broker>/portfolio/store_positions_to_db` into `<broker>.positions` and by
`bin/unified/orders/websocket_order_details`.

Orders, positions, trades and funds are polled every half second, except at Fyers, which is polled
more slowly - orders and positions every five seconds, trades every fifteen and funds every thirty - and
at Stoxkart, which documents a limit of one request a second and is polled every second.

### Quotes

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:quotes:subscriptions` | set | you | The instruments `bin/<broker>/instruments/websocket_quotes` subscribes to when none are passed on its command line. Zerodha has none: its feed subscribes to every instrument in `zerodha:instruments:master` |
| `<broker>:quotes:live` | hash, keyed by instrument name | `bin/<broker>/instruments/websocket_quotes` | The latest tick per instrument; Stoxkart's feed writes a tick only when it changed |
| `<broker>:quotes:instruments` | hash | `bin/<broker>/instruments/websocket_quotes` | Every subscribed token to its name, or to an empty string when unnamed; replaced whole at startup |
| `<broker>:quotes:stream` | stream, field `tick` | `bin/<broker>/instruments/websocket_quotes` | Every tick in arrival order, capped at about 1,000,000 |

Subscription members and hash fields are in the broker's own vocabulary: a Kite instrument token for
Zerodha, `EXCHANGE|TOKEN` for the Noren brokers and Kotak, a Fyers symbol, `EXCHANGE:TOKEN` for
Stoxkart, and so on. `quotes:live` is
keyed by the instrument's name where the broker's instrument file gives one (`NSE:RELIANCE`), and by
the token otherwise. It is not cleared at startup, so an instrument no longer subscribed keeps its last
tick.

The stream is read by `bin/<broker>/instruments/store_quotes_to_db` into `<broker>.ticks` and by `bin/unified/instruments/websocket_quotes`.
Ticks trimmed from it while the persister is stopped are lost to the database.

### Instruments

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:instruments:master` | hash, keyed by the table's natural key | `bin/<broker>/instruments/daily_feed` | Each instrument's row as a JSON array in column order |
| `<broker>:instruments:meta` | string | `bin/<broker>/instruments/daily_feed` | `{"download_date", "rows", "columns", "source_last_modified", "written_at"}`, with Kotak's `source` (the day's scrip master URL) and Wisdom Capital's `segments` in place of `source_last_modified` |

Written for all ten brokers, Stoxkart included, each morning by `unified-mapping.service`. The
field is the broker's own key for an instrument - Zerodha's `instrument_token`, Stoxkart's
`EXCHANGE:TOKEN` - and the column names are stored once in `meta` rather than in every row, which keeps
the hash near the file's own size. The hash is built under `<broker>:instruments:master:staging` and
swapped in at the end, so a reader sees yesterday's complete hash or today's, never one half-written.

## Unified

### Portfolio and orders

Each combiner reads the brokers' keys above, calls no broker, and writes one document in the shape the
REST API answers with. Every document carries `brokers`, saying for each broker whether its keys were
`ok`, `stale`, `missing` or `unreadable` and when they were stored, and `as_of`.

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:portfolio:positions` | string | `bin/unified/portfolio/positions`, every half second | `{"net", "day", "summary", "brokers", "as_of"}` |
| `unified:portfolio:holdings` | string | `bin/unified/portfolio/holdings`, every minute | `{"holdings", "summary", "brokers", "as_of"}` |
| `unified:portfolio:funds` | string | `bin/unified/portfolio/funds`, every half second | `{"summary", "pnl", "margin_breakdown", "cash_movement", "segments", "brokers", "as_of"}` |
| `unified:orders:orders` | string | `bin/unified/orders/api_order_details`, every half second | `{"orders", "summary", "brokers", "as_of"}` |
| `unified:orders:trades` | string | `bin/unified/orders/api_trade_details`, every half second | `{"trades", "summary", "brokers", "as_of"}` |
| `unified:orders:round_robin` | string | `POST /api/orders/place`, one `INCR` per checked order | A counter with no expiry; the broker whose turn it is is this count modulo the number of brokers not excluded |

### The order engine

These exist only when `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` is `engine`. The REST API then
stops calling brokers itself: it writes the order down and waits, and `bin/unified/orders/order_engine`
places it and pushes the answer back.

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:orders:intents:stream` | stream, field `intent` | `POST /api/orders/place` in engine mode | One accepted order awaiting placement, with `intent_id`, `created_at`, `deadline_at`, `reply_key`, `api_worker`, `synthetic_type` and the caller's `body` verbatim; capped at about 10,000 |
| `unified:orders:intents:result:<intent_id>` | list, `UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_RESULT_TTL_SECONDS` TTL | `bin/unified/orders/order_engine` | `{"body", "status"}`, the answer the waiting API worker pops |
| `unified:orders:engine:lock` | string, 30 s TTL, refreshed while it runs | `bin/unified/orders/order_engine` | The pid of the one engine allowed to run, so two engines cannot both place an order |
| `unified:orders:parents` | hash, keyed `parent_order_id`, expires 06:00 IST | `bin/unified/orders/order_engine` | Every parent order the engine is running, in the contract above |
| `unified:orders:parents:open` | set, expires 06:00 IST | `bin/unified/orders/order_engine` | The parents that have not finished, for a quick recovery scan |
| `unified:orders:children` | hash, keyed `broker:order_id`, expires 06:00 IST | `bin/unified/orders/order_engine` | Which parent a broker's order belongs to, so an order update finds its owner |

The last three are a cache, not the record. `unified.synthetic_order_events` holds every transition, and the engine
rebuilds all three from it on start, so a flushed Redis costs a slower start rather than a lost position. They expire
at 06:00 IST like the brokers' merged hashes, which is the same boundary the recovery scan reads from.

The intents are a stream rather than a list so that an engine restart finds the orders written while it
was down, and so that a backlog can be read with `XINFO GROUPS` like every other queue here. The engine
reads them as the consumer group `engine`.

The result is a list rather than a string because a string cannot be blocked on: the worker waits with
`BLPOP`, which takes the answer and removes the key in one step, so the TTL only ever expires an answer
nobody came back for. A worker that gives up first answers outcome `unknown` with HTTP 504, and the
engine refuses to place an intent whose `deadline_at` passed more than
`UNIFIED_BROKER_INTERFACE_API_ORDER_ENGINE_STALE_INTENT_SECONDS` ago, so a restart cannot fire a stale
order into a market that has moved.

### Order and position updates

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:order-updates:stream` | stream, field `update` | `bin/unified/orders/websocket_order_details` | Every broker's order updates, in the REST order contract with `broker`, `instrument_id` and `observed_at`; capped at about 50,000 |
| `unified:order-updates` | hash, keyed `broker:order_id` | `bin/unified/orders/websocket_order_details` | The latest update per order |
| `unified:positions_updates:stream` | stream, field `position` | `bin/unified/orders/websocket_order_details` | Every position update, in the REST position contract with `broker`, `position_key`, `basis` and `observed_at`; capped at about 50,000 |
| `unified:positions_updates` | hash, keyed `broker:position_key` | `bin/unified/orders/websocket_order_details` | The latest update per position |

The streams are read by `bin/unified/orders/store_orders_to_db` into `unified.order_updates` and
`bin/unified/portfolio/store_positions_to_db` into `unified.positions`. The two hashes expire at 06:00 IST like the
brokers' merged hashes, and an update observed before the latest 06:00 goes to the stream but not into
the hash.

### Quotes

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:quotes:live` | hash, keyed by `instrument_id` | `bin/unified/instruments/websocket_quotes` | The latest unified quote per instrument, from the one broker that owns it |
| `unified:quotes:stream` | stream, field `quote` | `bin/unified/instruments/websocket_quotes` | Every quote written to the hash, capped at about 1,000,000 |
| `unified:quotes:fetched` | hash, per-field expiry of two days | the REST API | Quotes fetched from a broker when the live quote was not good enough, in the same document shape |
| `unified:quotes:stats` | string | `bin/unified/instruments/websocket_quotes` | The counts: received, unresolved, out of session, not owner, no price, duplicate, written |
| `unified:quotes:unresolved` | hash, keyed `broker:token:reason` | `bin/unified/instruments/websocket_quotes` | How many times a token failed to resolve to one instrument: once when first seen, then once per ten-minute retry |

A quote is the [unified quote](contracts.md#the-unified-quote) document. A quote whose
owner went silent with no healthy backup stays in `quotes:live` with `stale` true; quotes stale for a
week are removed. The stream is read by `bin/unified/instruments/store_quotes_to_db` into `unified.ticks`. The REST API
answers from the more recent of `quotes:live` and `quotes:fetched`, and never writes into
`quotes:live`, whose ownership rules belong to `bin/unified/instruments/websocket_quotes`.

### Session, profiles and details

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:session:status` | string | `bin/unified/session/connect`, `disconnect` | `{"status", "access-token", "last_login", "expires_at"}` for the application's own token |
| `unified:user:details` | string | `bin/unified/user/details`, every minute | One object with a key per broker and that broker's profile `data`, or null |
| `unified:details:users` | string | `bin/unified/user/unified_details`, every minute | The MongoDB `user_details` collection as one JSON array |
| `unified:details:brokers` | string | `bin/unified/user/unified_details` | `broker_details`, likewise |
| `unified:details:exchanges` | string | `bin/unified/user/unified_details` | `exchange_details`, likewise |

The three `details` keys are written together in one `MULTI`. MongoDB stays the store of record, and
the REST API falls back to it when a key is missing.

### Instruments

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:instruments` | hash, keyed by `instrument_id` | `bin/unified/instruments/map` | Every instrument mapped on the date, as a JSON array in the order `columns.instruments` gives |
| `unified:broker_mappings` | hash, keyed `broker:instrument_id` | `bin/unified/instruments/map` | `[broker_token, broker_symbol, order_symbol, lot_size, tick_size]` |
| `unified:broker_tokens` | hash, keyed `broker:broker_token` | `bin/unified/instruments/map` | A JSON array of the instrument ids that token names on the date |
| `unified:instrument_symbols` | hash, keyed `segment:SYMBOL` | `bin/unified/instruments/map` | The instrument id, for a broker that sends no token |
| `unified:mapping:meta` | string | `bin/unified/instruments/map` | `mapping_date`, the four counts, `columns` and `written_at` |

`unified:instruments` columns are `exchange`, `segment`, `shape`, `symbol`, `underlying_symbol`,
`expiry_date`, `strike_price`, `option_type`, `first_seen_date` and `last_seen_date`. A token is not
unique within a broker, so `broker_mappings` is keyed by the instrument, and `broker_tokens` is the
reverse lookup the combiners and `bin/unified/instruments/websocket_quotes` resolve with; it usually names one instrument,
and several where a broker reuses a token across an exchange's scrip files. All four hashes are built
under `:staging` keys and swapped in together with the meta, so a reader sees yesterday's complete
cache or today's, never a mix. For one day that is about half a million instruments and two million
mappings. See [Instrument mapping](../guides/instrument-mapping.md).

#### The REST API's catalogue

The [mapping cache](../guides/instrument-mapping.md#the-three-tier-cache) the REST API's instrument
routes read, under the `unified:catalogue:` prefix. `bin/unified/instruments/map` warms it from the
unified tables after every mapping and clears every other date's keys. A warm that fails is logged and
does not fail the run; the API reads the unified tables until the next warm succeeds.

| Key | Type | Keyed by | Holds |
| --- | --- | --- | --- |
| `unified:catalogue:current_date` | string | - | The mapping date the dated keys below belong to |
| `unified:catalogue:warm_identifier` | string | - | A random identifier set with `current_date` on every warm, so a process holding catalogue data in memory can tell a re-run warm of the same date from the one it read |
| `unified:catalogue:<date>:identity` | hash | `instrument_id` | That instrument's exchange, segment, shape and identity fields |
| `unified:catalogue:<date>:tokens:<broker>` | hash | broker token | The comma-joined ids of the instruments that token names; `PUT /api/orders/modify` reads it to find a stored order's instrument |
| `unified:catalogue:<date>:order_handles` | hash | `instrument_id` | What a broker needs to place an order on it |
| `unified:catalogue:<date>:contract_sizes` | hash | `instrument_id` | A currency or commodity contract's `units_per_lot`, `status` and `tradeable`, copied from `unified.contract_sizes` |
| `unified:catalogue:<date>:additional_attributes` | hash | `instrument_id` | Each broker's extra instrument attributes, copied from `unified.broker_mappings.attributes`; what `/api/instruments/additional_details` serves |
| `unified:catalogue:<date>:catalogue:<segment>` | sorted set, scores 0 | lexical | `NAME\|expiry\|strike\|option_type\|instrument_id` per instrument |
| `unified:catalogue:<date>:names:<segment>` | sorted set, scores 0 | lexical | The segment's distinct symbols or underlyings |
| `unified:catalogue:<date>:seen` | hash | `instrument_id` | `first_seen_date\|last_seen_date` |
| `unified:catalogue:<date>:segments` | hash | segment | Instruments in the segment; written last, so its presence means the catalogue is complete |

The prefix is not `unified:mapping:` because a warm deletes every key under its prefix but the current
date's, and `unified:mapping:meta` belongs to `bin/unified/instruments/map`' own cache.

### Runs and the candle cache

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:prices:last_run` | string | `bin/unified/instruments/price_history` | The outcome of the last run, as JSON |
| `unified:prices:cache:<instrument_id>:<interval>:<basis>:<known_as_of or latest>` | string, 86400 s TTL | The REST API's `/api/instruments/prices` | `{last_run, built_at, from, to, columns, candles}` - the widest range of candles read for that series |

The API keeps a copy of every answer `/prices` reads from the database, and serves a later request by
slicing that copy when its range falls inside the copy's. `basis` is `adjusted`, `unadjusted` or
`as_served`, so adjusted and raw prices, and each `known_as_of` cut-off, are cached apart. `last_run` is
the `finished` time the price history run had when the copy was made: a copy stamped with an earlier run
is ignored and read again, so a load, a correction or a rebuilt adjustment factor drops every copy. An
entry over two megabytes is not stored at all. See [the REST API guide](../guides/rest-api.md#candles-are-cached-in-redis).

## Shared with MongoDB

| Key | Type | Field | Value |
| --- | --- | --- | --- |
| `settings` | hash | broker name | The broker's settings document as JSON |
| `last_login` | hash | broker name, or `unified_broker_interface` | The last login document as JSON |

`settings` is copied in when a broker's API class is constructed. `last_login` is written by a login,
after MongoDB, and read on every REST request by the broker's API class - so it is the one place the
token in force is read from, and a login by any process takes effect for every other process on its
next request. When a field is empty it is filled from MongoDB with `HSETNX`, which cannot overwrite a
login that lands first.

Wisdom Capital's field carries a second token beside the first. Symphony XTS issues one token for the
interactive application and another for market data, so its document also holds `market_data_access_token`,
`market_data_user_id` and `market_data_last_login`. Both are established when `WisdomCapitalAPI` is
constructed, and each login merges into the stored document rather than replacing it, so establishing one
session never erases the other's token.

The field `unified_broker_interface` holds the application's own token, written by `bin/unified/session/connect`
and the REST API's connect as `{"broker_name", "access_token", "last_login", "expires_at"}`. A logout
sets `access_token` and `expires_at` to null. If the Redis write fails the field is deleted instead, so
a reader falls back to MongoDB rather than trusting a token that has since been replaced or revoked.

## Reading them by hand

```bash
redis-cli GET zerodha:session:status
redis-cli HGET zerodha:quotes:live "NSE:RELIANCE" | python3 -m json.tool
redis-cli XINFO GROUPS zerodha:quotes:stream            # each group's lag and pending count
redis-cli XREVRANGE unified:order-updates:stream + - COUNT 5
redis-cli GET unified:portfolio:positions | python3 -m json.tool
redis-cli HGET unified:broker_tokens dhan:2885
redis-cli XINFO GROUPS unified:orders:intents:stream    # how far behind the order engine is
```

## Login lock and request log

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `ubi:login:<broker>` | string, 300 s TTL | `ensure_session` | The lock held while one process logs a broker in, recording the holder's pid |
| `ubi:login-attempt:<broker>`, `ubi:login-ok:<broker>` | string | `ensure_session` | When a login was last attempted and last succeeded, so only genuine retries are rate limited |
| `wisdom_capital:session:marketdata:lock` | string, 120 s TTL | `WisdomCapitalAPI` | The lock held while one process replaces Wisdom Capital's market data token, recording the holder's pid. The token itself lives in the `last_login` hash |
| `broker_api_calls` | list | every broker's API class, only when called with `verbose` | Each request made |

`ensure_session` in `stock_brokers/api/utilities/session.py` is the login `BrokerCandles` uses by default and the one
IND Money's instrument ingester uses; the `bin/<broker>/` scripts log in through the broker's API class.

Nothing is published on pub/sub. A process that wants live data reads the latest values from the hashes
above and follows a stream with a consumer group of its own, as the persisters and the unified scripts do.
