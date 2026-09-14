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

`<broker>` is one of `dhan`, `flattrade`, `fyers`, `groww`, `indmoney`, `kotak`, `shoonya`,
`wisdom_capital` and `zerodha`. Stoxkart writes only its instrument keys.

### Session and profile

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:session:status` | string | `bin/<broker>/login`, `logout` | `{"status", "access-token", "last_login"}`, replaced on every run |
| `<broker>:user:details` | string | `bin/<broker>/user-profile` | `{"timestamp", "status", "code", "data"}`, the broker's profile under `data` |

`status` is `success`, `failure` or `logged out`. On success `last_login` is when the token in force was
issued, which is earlier than the run when the stored session was still good; on failure it is when the
attempt was made; after a logout both it and `access-token` are null. A broker logout only marks this
key - nothing is sent to the broker, because its logout endpoint would invalidate the one token every
other process is using.

The profile is polled every minute. Wisdom Capital's is fetched once a day, since it allows about one
profile call a day, and Kotak, which has no profile endpoint, has its profile written by
`bin/kotak/login` from the login response, on a run that actually logged in.

`wisdom_capital:session:marketdata` holds Wisdom Capital's separate market data token as
`{"token", "userID"}`, shared by `bin/wisdom_capital/quotes` and `bin/wisdom_capital/historical_prices`,
with `wisdom_capital:session:marketdata:lock` held while one of them replaces a refused token.

### Orders

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:orders:orders` | hash, keyed by the broker's order id | `bin/<broker>/orders` and `bin/<broker>/order_updates` | `{"observed_at", "source", "order", "data"}` per order |
| `<broker>:orders:orders:polled_at` | string | `bin/<broker>/orders` | When the order book was last read successfully, epoch seconds |
| `<broker>:orders:trades` | string | `bin/<broker>/trades` | `{"timestamp", "status", "code", "data"}`, the day's trade book under `data` |
| `<broker>:order-updates:stream` | stream, field `update` | `bin/<broker>/order_updates` | Every order update as `{"timestamp", "data"}`, capped at about 20,000 |

`orders:orders` is the one hash for a broker's orders, merged from two writers. `source` is `rest` or
`websocket`, `order` is the order normalized onto the shared vocabulary - status `PENDING`, `OPEN`,
`COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED` - and `data` is the broker's own order exactly as sent.
A websocket update always replaces its order's entry; a polled row replaces it only when the entry was
observed before the poll's request was sent, so an update that arrived while the request was in flight
is never overwritten by the older snapshot. The check and the write run together as one Redis script.

`polled_at` exists because Redis keeps no empty hash, so the hash alone cannot say that an empty book
was read. Both keys expire at 06:00 IST, and every write moves that to the next 06:00, so yesterday's
orders stay readable overnight and the first poll of the day starts afresh.

The stream is written by the nine brokers' `order_updates` scripts. It is read by
`bin/<broker>/persist_orders` into `<broker>.order_updates`, and by `bin/unified/order_updates`.
Flattrade's `order_updates` script exists but is not run, since Flattrade permits one websocket per
session and its quotes script holds it.

### Portfolio

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:portfolio:positions` | hash, keyed per position | `bin/<broker>/positions`, and `order_updates` where the broker streams positions | `{"observed_at", "source", "position", "data"}` per position |
| `<broker>:portfolio:positions:polled_at` | string | `bin/<broker>/positions` | When the positions were last read successfully, epoch seconds |
| `<broker>:positions_updates:stream` | stream, field `position` | `bin/<broker>/order_updates` | Every position update as `{"timestamp", "data"}`, capped at about 20,000 |
| `<broker>:portfolio:holdings` | string | `bin/<broker>/holdings` | `{"timestamp", "status", "code", "data"}`, polled every minute |
| `<broker>:portfolio:funds` | string | `bin/<broker>/funds` | `{"timestamp", "status", "code", "data"}` |

The positions hash follows the orders hash exactly - the same merge rule, the same `polled_at`, the same
06:00 IST expiry. Its field names a position the way the broker holds one, such as Zerodha's
`NET:exchange:instrument_token:product` and `DAY:...`, Kotak's `exSeg:tok:prod` or Fyers'
`symbol:product`, so a position lands on one field whichever script wrote it.

Only Fyers, Groww, Kotak and Wisdom Capital stream positions, so only they have a
`positions_updates:stream`, read by `bin/<broker>/persist_positions` into `<broker>.positions` and by
`bin/unified/order_updates`.

Orders, positions, trades and funds are polled every half second, except at Fyers, which is polled
more slowly - orders and positions every five seconds, trades every fifteen and funds every thirty.

### Quotes

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:quotes:subscriptions` | set | you | The instruments `bin/<broker>/quotes` subscribes to when none are passed on its command line |
| `<broker>:quotes:live` | hash, keyed by instrument name | `bin/<broker>/quotes` | The latest tick per instrument |
| `<broker>:quotes:instruments` | hash | `bin/<broker>/quotes` | Every subscribed token to its name, or to an empty string when unnamed; replaced whole at startup |
| `<broker>:quotes:stream` | stream, field `tick` | `bin/<broker>/quotes` | Every tick in arrival order, capped at about 100,000 |

Subscription members and hash fields are in the broker's own vocabulary: a Kite instrument token for
Zerodha, `EXCHANGE|TOKEN` for the Noren brokers and Kotak, a Fyers symbol, and so on. `quotes:live` is
keyed by the instrument's name where the broker's instrument file gives one (`NSE:RELIANCE`), and by
the token otherwise. It is not cleared at startup, so an instrument no longer subscribed keeps its last
tick.

The stream is read by `bin/<broker>/persist_ticks` into `<broker>.ticks` and by `bin/unified/quotes`.
Ticks trimmed from it while the persister is stopped are lost to the database.

### Instruments

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `<broker>:instruments:master` | hash, keyed by the table's natural key | `bin/<broker>/instruments` | Each instrument's row as a JSON array in column order |
| `<broker>:instruments:meta` | string | `bin/<broker>/instruments` | `{"download_date", "rows", "columns", "source_last_modified", "written_at"}` |

Written for all ten brokers, Stoxkart included, each morning by `unified-instruments.service`. The
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
| `unified:portfolio:positions` | string | `bin/unified/positions`, every half second | `{"net", "day", "summary", "brokers", "as_of"}` |
| `unified:portfolio:holdings` | string | `bin/unified/holdings`, every minute | `{"holdings", "summary", "brokers", "as_of"}` |
| `unified:portfolio:funds` | string | `bin/unified/funds`, every half second | `{"summary", "pnl", "margin_breakdown", "cash_movement", "segments", "brokers", "as_of"}` |
| `unified:orders:orders` | string | `bin/unified/orders`, every half second | `{"orders", "summary", "brokers", "as_of"}` |
| `unified:orders:trades` | string | `bin/unified/trades`, every half second | `{"trades", "summary", "brokers", "as_of"}` |

### Order and position updates

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:order-updates:stream` | stream, field `update` | `bin/unified/order_updates` | Every broker's order updates, in the REST order contract with `broker`, `instrument_id` and `observed_at`; capped at about 50,000 |
| `unified:order-updates` | hash, keyed `broker:order_id` | `bin/unified/order_updates` | The latest update per order |
| `unified:positions_updates:stream` | stream, field `position` | `bin/unified/order_updates` | Every position update, in the REST position contract with `broker`, `position_key`, `basis` and `observed_at`; capped at about 50,000 |
| `unified:positions_updates` | hash, keyed `broker:position_key` | `bin/unified/order_updates` | The latest update per position |

The streams are read by `bin/unified/persist_orders` into `unified.order_updates` and
`bin/unified/persist_positions` into `unified.positions`. The two hashes expire at 06:00 IST like the
brokers' merged hashes, and an update observed before the latest 06:00 goes to the stream but not into
the hash.

### Quotes

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:quotes:live` | hash, keyed by `instrument_id` | `bin/unified/quotes` | The latest unified quote per instrument, from the one broker that owns it |
| `unified:quotes:stream` | stream, field `quote` | `bin/unified/quotes` | Every quote written to the hash, capped at about 200,000 |
| `unified:quotes:fetched` | hash, per-field expiry of two days | the REST API | Quotes fetched from a broker when the live quote was not good enough, in the same document shape |
| `unified:quotes:stats` | string | `bin/unified/quotes` | The counts: received, unresolved, out of session, not owner, no price, duplicate, written |
| `unified:quotes:unresolved` | hash, keyed `broker:token:reason` | `bin/unified/quotes` | How many ticks could not be resolved to one instrument |

A quote is the [unified quote](contracts.md#the-unified-quote) document. A quote whose
owner went silent with no healthy backup stays in `quotes:live` with `stale` true; quotes stale for a
week are removed. The stream is read by `bin/unified/persist_ticks` into `unified.ticks`. The REST API
answers from the more recent of `quotes:live` and `quotes:fetched`, and never writes into
`quotes:live`, whose ownership rules belong to `bin/unified/quotes`.

### Session, profiles and details

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:session:status` | string | `bin/unified/login`, `logout` | `{"status", "access-token", "last_login", "expires_at"}` for the application's own token |
| `unified:user:details` | string | `bin/unified/user-profile`, every minute | One object with a key per broker and that broker's profile `data`, or null |
| `unified:details:users` | string | `bin/unified/details`, every minute | The MongoDB `user_details` collection as one JSON array |
| `unified:details:brokers` | string | `bin/unified/details` | `broker_details`, likewise |
| `unified:details:exchanges` | string | `bin/unified/details` | `exchange_details`, likewise |

The three `details` keys are written together in one `MULTI`. MongoDB stays the store of record, and
the REST API falls back to it when a key is missing.

### Instruments

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:instruments` | hash, keyed by `instrument_id` | `bin/unified/map_instruments` | Every instrument mapped on the date, as a JSON array in the order `columns.instruments` gives |
| `unified:broker_mappings` | hash, keyed `broker:instrument_id` | `bin/unified/map_instruments` | `[broker_token, broker_symbol, order_symbol, lot_size, tick_size]` |
| `unified:broker_tokens` | hash, keyed `broker:broker_token` | `bin/unified/map_instruments` | A JSON array of the instrument ids that token names on the date |
| `unified:instrument_symbols` | hash, keyed `segment:SYMBOL` | `bin/unified/map_instruments` | The instrument id, for a broker that sends no token |
| `unified:mapping:meta` | string | `bin/unified/map_instruments` | `mapping_date`, the four counts, `columns` and `written_at` |

`unified:instruments` columns are `exchange`, `segment`, `shape`, `symbol`, `underlying_symbol`,
`expiry_date`, `strike_price`, `option_type`, `first_seen_date` and `last_seen_date`. A token is not
unique within a broker, so `broker_mappings` is keyed by the instrument, and `broker_tokens` is the
reverse lookup the combiners and `bin/unified/quotes` resolve with; it usually names one instrument,
and several where a broker reuses a token across an exchange's scrip files. All four hashes are built
under `:staging` keys and swapped in together with the meta, so a reader sees yesterday's complete
cache or today's, never a mix. For one day that is about half a million instruments and two million
mappings. See [Instrument mapping](../guides/instrument-mapping.md).

#### The REST API's catalogue

The [mapping cache](../guides/instrument-mapping.md#the-three-tier-cache) the REST API's instrument
routes read, under the `unified:catalogue:` prefix. `bin/unified/map_instruments` warms it from the
unified tables after every mapping and clears every other date's keys. A warm that fails is logged and
does not fail the run; the API reads the unified tables until the next warm succeeds.

| Key | Type | Keyed by | Holds |
| --- | --- | --- | --- |
| `unified:catalogue:current_date` | string | - | The mapping date the dated keys below belong to |
| `unified:catalogue:<date>:identity` | hash | `instrument_id` | That instrument's exchange, segment, shape and identity fields |
| `unified:catalogue:<date>:tokens:<broker>` | hash | broker token | The `instrument_id` that token resolves to |
| `unified:catalogue:<date>:order_handles` | hash | `instrument_id` | What a broker needs to place an order on it |
| `unified:catalogue:<date>:catalogue:<segment>` | sorted set, scores 0 | lexical | `NAME\|expiry\|strike\|option_type\|instrument_id` per instrument |
| `unified:catalogue:<date>:names:<segment>` | sorted set, scores 0 | lexical | The segment's distinct symbols or underlyings |
| `unified:catalogue:<date>:seen` | hash | `instrument_id` | `first_seen_date\|last_seen_date` |
| `unified:catalogue:<date>:segments` | hash | segment | Instruments in the segment; written last, so its presence means the catalogue is complete |

The prefix is not `unified:mapping:` because a warm deletes every key under its prefix but the current
date's, and `unified:mapping:meta` belongs to `bin/unified/map_instruments`' own cache.

### Runs

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `unified:prices:last_run` | string | `bin/unified/historical_prices` | The outcome of the last run, as JSON |

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

The field `unified_broker_interface` holds the application's own token, written by `bin/unified/login`
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
```

## Login lock and request log

| Key | Type | Written by | Holds |
| --- | --- | --- | --- |
| `ubi:login:<broker>` | string, 300 s TTL | `ensure_session` | The lock held while one process logs a broker in, recording the holder's pid |
| `ubi:login-attempt:<broker>`, `ubi:login-ok:<broker>` | string | `ensure_session` | When a login was last attempted and last succeeded, so only genuine retries are rate limited |
| `broker_api_calls` | list | every broker's API class, only when called with `verbose` | Each request made |

`ensure_session` in `stock_brokers/api/session.py` is the login `BrokerCandles` uses by default and the one
IND Money's instrument ingester uses; the `bin/<broker>/` scripts log in through the broker's API class.

Nothing is published on pub/sub. A process that wants live data reads the latest values from the hashes
above and follows a stream with a consumer group of its own, as the persisters and the unified scripts do.
