# Broker scripts

Each broker has a directory of small, self-contained scripts under `bin/<broker>/`. A script does one
thing - log in, poll the order book, stream quotes, persist a stream - and carries everything it needs
to do it: it logs in by itself through the broker's API class, logs in again when its token is refused,
and writes what it reads to Redis under keys named for the broker. No script depends on another process
running.

These scripts are the only part of the project that talks to a broker. The
[unified scripts](unified-scripts.md) in `bin/unified/` read what these write and combine it across
brokers, and never call a broker themselves.

```bash
bin/zerodha/login                         # log in, record the outcome
bin/zerodha/orders                        # poll the order book every half second
redis-cli HGETALL zerodha:orders:orders
systemctl --user enable --now zerodha@orders.service
```

## The scripts

| Script | Kind | What it does |
| --- | --- | --- |
| `login` | once | Confirms the stored session works, logging in when it does not, and records the outcome in `<broker>:session:status` |
| `logout` | once | Marks the broker logged out in `<broker>:session:status`. Nothing is sent to the broker |
| `user-profile` | poll | Writes the account's profile to `<broker>:user:details` |
| `orders` | poll | Merges the day's order book into the hash `<broker>:orders:orders` |
| `trades` | poll | Writes the day's trade book to `<broker>:orders:trades` |
| `holdings` | poll | Writes the holdings to `<broker>:portfolio:holdings` |
| `positions` | poll | Merges the positions into the hash `<broker>:portfolio:positions` |
| `funds` | poll | Writes the funds and margins to `<broker>:portfolio:funds` |
| `quotes` | websocket | Streams market quotes into `<broker>:quotes:live` and the stream `<broker>:quotes:stream` |
| `order_updates` | websocket | Merges order updates, and position updates where the broker sends them, into the same hashes the pollers fill, and appends each to a stream |
| `instruments` | once | Downloads the day's instrument master into `<broker>.instruments` and `<broker>:instruments:master` |
| `historical_prices` | worker | Works a resumable queue of historical candle downloads into `<broker>.price_history` |
| `persist_ticks` | consumer | Drains `<broker>:quotes:stream` into `<broker>.ticks` |
| `persist_orders` | consumer | Drains `<broker>:order-updates:stream` into `<broker>.order_updates` |
| `persist_positions` | consumer | Drains `<broker>:positions_updates:stream` into `<broker>.positions` |

Every script's module docstring is its full reference: the endpoint it calls, every field it writes and
how each is derived from the broker's own names, and its exit codes. Only `quotes`, `instruments`,
`historical_prices` and the persisters take options; `login`, `logout` and the pollers take none.

## Which broker has which

| Script | dhan | zerodha | flattrade | shoonya | fyers | indmoney | wisdom_capital | groww | kotak | stoxkart |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| `login`, `logout` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `user-profile` | yes | yes | yes | yes | yes | yes | yes | yes | - | yes |
| `orders`, `trades`, `holdings`, `positions`, `funds` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `quotes` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `order_updates` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `persist_ticks` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `persist_orders` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `persist_positions` | - | - | - | - | yes | - | yes | yes | yes | - |
| `instruments` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `historical_prices` | yes | yes | yes | yes | yes | yes | yes | - | - | - |

The gaps follow the brokers:

- **Kotak** has no profile endpoint. Its profile arrives only in the login response, so `bin/kotak/login`
  writes `kotak:user:details` on a run that actually logged in, and there is no `user-profile` script.
- **Groww, Kotak and Stoxkart** have no `historical_prices`, and so no `<broker>-historical-prices.service`.
- **`persist_positions`** exists only for the four brokers whose `order_updates` socket carries
  positions: Fyers, Wisdom Capital, Groww (derivatives positions only) and Kotak. The other six stream
  orders alone, and their positions come only from the `positions` poller.
- **Stoxkart**'s `quotes` and `order_updates` use the two websockets Stoxkart's own trading website
  uses, found by watching `webtrade.stoxkart.com` in Chrome DevTools on 2026-09-15, rather than the
  documented quote websocket, which could not be reached, and the documented Postback URL, which needs a
  public web server. See [Stoxkart's quote feed](#stoxkarts-quote-feed) and
  [Stoxkart's order socket](#stoxkarts-order-socket).

## Sessions

`login` constructs the broker's API class, which probes an authenticated endpoint with the stored token
and runs the real login only when that probe fails. A new token is written to MongoDB and to the Redis
`last_login` hash, which is where every other script reads it. The endpoint is then asked once more, so a
success means a session that has actually been used. The outcome goes to `<broker>:session:status`:

```json
{"status": "success", "access-token": "<token>", "last_login": "2026-09-14 08:30:02.123456"}
{"status": "failure", "access-token": null, "last_login": "2026-09-14 08:30:02.123456"}
```

On success `last_login` is when the token in force was issued, which is earlier than the run when the
stored session was still good. `login` exits 1 on any failure, so its unit can retry.

`logout` writes `{"status": "logged out", "access-token": null, "last_login": null}` and nothing more.
No broker's logout endpoint is called: it would invalidate the one token every other script is using.
The stored token is left alone and stays valid until it expires.

Every other script handles its own session. A poller that is refused - a Kite `TokenException`, a Noren
"Session Expired", a Fyers code -8, -15, -16 or -17 - logs in again **before** its next request, rather
than carrying on with a dead token. A websocket script reads the token afresh on every connect; a
refused handshake, or a socket that fails to open six times running, logs in again before reconnecting,
and other reconnects back off from 1 to 60 seconds. A script exits non-zero only when it cannot
recover: a login that fails, or a socket still refused straight after logging in again.

!!! warning "Brokers that issue one token per session"

    At Zerodha every login invalidates the token before it. `ZerodhaAPI` therefore probes with the newest
    stored token first and logs in only when that fails too, so a refusal caused by another process's
    login is recovered without a second login, and `bin/zerodha/quotes` lets only one socket log in at a
    time. Two independent morning logins at such a broker invalidate each other.

Fyers can refuse a request inside an HTTP 200, so its scripts check the body and confirm a new session
against the profile. A Cloudflare ban in front of Fyers pauses a poller for thirty minutes and a rate
limit for five, instead of logging in, because every refused request extends a ban.

## Polling

| Script | Interval | Exceptions |
| --- | --- | --- |
| `orders` | 0.5 s | Fyers 5 s, Stoxkart 1 s |
| `positions` | 0.5 s | Fyers 5 s, Stoxkart 1 s |
| `trades` | 0.5 s | Fyers 15 s, Stoxkart 1 s |
| `funds` | 0.5 s | Fyers 30 s, Stoxkart 1 s |
| `holdings` | 60 s | |
| `user-profile` | 60 s | Wisdom Capital once a day, retried after an hour when a call fails, since it allows about one profile call a day |

Fyers polls more slowly because it refuses more than a handful of requests a second per app. Stoxkart
documents a limit of one request a second for its order book, positions, trade book and funds, so those
pollers wait a second between requests. The limit was not enforced on 2026-09-15, when six back-to-back
requests all succeeded, but the pollers keep to it. A dead Stoxkart session is refused with HTTP 401 and
the code `AuthorizationError` ("Session token is wrong"), and the script logs in again before its next
request.

A failed poll is logged and leaves the key as it was. At two cycles a second a line per cycle would be
about 170,000 lines a day per script, so the half-second pollers report through
`utilities/poll_reporter.py`: `PollReporter` logs a message when it differs from the last one logged at
that level, and otherwise repeats it once every 60 seconds. The journal shows every change and a steady
heartbeat while nothing changes.

### Snapshot keys

`user-profile`, `trades`, `holdings` and `funds` write the whole response with SET, replacing the one
before, as one JSON string:

```text
{"timestamp": …, "status": …, "code": …, "data": <the broker's own payload>}
```

`data` is the broker's payload as it arrived - Kite's margins with `equity` and `commodity` blocks,
Fyers' `fund_limit` rows, Noren's limits - and each script's docstring lists its fields. An empty book
or an account holding nothing is written too, so an empty `data` is an answer rather than a gap.

### Orders and positions

Orders and positions each have **one hash per broker**, written by two scripts: the REST poller, and
`order_updates` from the broker's websocket. Every value has the same envelope:

```text
{"observed_at": <epoch>, "source": "rest" | "websocket", "order": <normalized order>, "data": <the broker's order>}
{"observed_at": <epoch>, "source": "rest" | "websocket", "position": <normalized position>, "data": <the broker's row>}
```

`data` is the broker's own row or message. `order` and `position` are normalized onto the same fields
on both sides, even where a broker names things differently in its order book and its update stream, so
they read the same whichever script wrote them - for orders `order_id`,
`status`, `transaction_type`, `product`, `order_type`, the quantities and prices, and timestamps as ISO
with the IST offset, with statuses on one vocabulary: `PENDING`, `OPEN`, `COMPLETE`, `CANCELLED`,
`REJECTED` and `EXPIRED`.

Stoxkart's order entries carry one more field, a top-level `variety` beside `data`, such as `NORMAL`,
`AMO` or `BO` in upper case. The REST API's cancel endpoint builds Stoxkart's cancel URL from it. It is
kept apart from `data` because Stoxkart's order socket reported `NORMAL` for after-market orders whose
order book row said `AMO`. The two scripts fill it in differently:

- `bin/stoxkart/orders` copies the order book row's `variety`.
- `bin/stoxkart/order_updates` keeps an `AMO` or `BO` variety already stored for the order, reads `AMO`
  from a status starting with `AMO`, and otherwise uses the update's own `variety`.

**Which write wins.** A websocket update always replaces its entry. A polled row replaces an entry only
when that entry was observed before the poll's request was sent, so an update arriving while a request
was in flight is never overwritten by the older snapshot. The check and the write run together in one
Redis script, and a polled row's `observed_at` is when its request was sent.

**Daily reset.** Both hashes expire at 06:00 IST, and every write moves that to the next 06:00, so the
previous day's entries stay readable overnight and nothing is removed during the day.

**`:polled_at`.** Each successful poll also writes its request time, in epoch seconds, to
`<broker>:orders:orders:polled_at` or `<broker>:portfolio:positions:polled_at`, expiring with the hash.
Redis keeps no empty hash, so without it a day with no orders could not be told apart from a poller that
is not running. The unified combiners judge freshness from it.

Orders are keyed by the broker's order id (`order_id`, `norenordno`, `nOrdNo`, `AppOrderID`,
`growwOrderId`, and `order_id` at Stoxkart). Positions are keyed by what identifies a position at that broker:

| Broker | Field | Example |
| --- | --- | --- |
| zerodha | `NET` or `DAY`, exchange, token, product | `NET:NSE:738561:CNC` |
| wisdom_capital | `NET` or `DAY`, segment, instrument id, product | `NET:NSEFO:35001:NRML` |
| dhan | segment, security id, product | `NSE_EQ:2885:CNC` |
| flattrade, shoonya | exchange, token, product | `NSE:2885:C` |
| indmoney | exchange, token, product | `NSE:2885:INTRADAY` |
| fyers | symbol, product | `NSE:INFY-EQ:INTRADAY` |
| groww | exchange, contract, product | `NSE:NIFTY26SEP26000CE:NRML` |
| kotak | segment, token, product | `nse_cm:11536:CNC` |
| stoxkart | exchange, token, product type; `DAY:` in front for a day list, which Stoxkart has never sent | `NSE:760946:DELIVERY` |

## Websocket feeds

### Quotes

`quotes` logs in, opens its own connections and decodes the broker's packets itself. It writes three keys:

| Key | Type | Holds |
| --- | --- | --- |
| `<broker>:quotes:live` | hash | The latest tick per instrument as JSON, keyed by the instrument's name (or its token when unnamed). Not cleared at startup |
| `<broker>:quotes:instruments` | hash | Every subscribed token to its name. Replaced whole at startup |
| `<broker>:quotes:stream` | stream | Every tick in arrival order as a `tick` field, capped at about 100,000 entries |

`--per-socket` sets how many instruments one connection carries, and `--tokens` subscribes to a list
instead of the subscription set. Kite allows three connections per api key and `order_updates` holds one,
so `bin/zerodha/quotes` uses at most two.

### Adding a subscription

Without `--tokens`, a feed subscribes to the members of the set `<broker>:quotes:subscriptions`, read when
it starts. Add the instrument in the broker's own format, then restart the feed:

```bash
redis-cli SADD zerodha:quotes:subscriptions 738561 408065
systemctl --user restart zerodha@quotes
```

| Broker | Member format | Example |
| --- | --- | --- |
| zerodha | Kite `instrument_token` | `738561` |
| dhan | `SEGMENT:SECURITY_ID` - `NSE_EQ`, `NSE_FNO`, `NSE_CURRENCY`, `BSE_EQ`, `BSE_FNO`, `BSE_CURRENCY`, `MCX_COMM`, `IDX_I` | `NSE_EQ:2885` |
| flattrade | `EXCHANGE|TOKEN` - `NSE`, `NFO`, `CDS`, `MCX`, `BSE`, `BFO` | `NSE|2885` |
| shoonya | `EXCHANGE|TOKEN` - as Flattrade, plus `NCX` | `MCX|565899` |
| fyers | Fyers symbol with its exchange | `NSE:SBIN-EQ` |
| indmoney | `SEGMENT:TOKEN` - `NSE`, `BSE`, `NFO`, `BFO`, `NIDX`, `BIDX` | `NSE:2885` |
| wisdom_capital | `SEGMENT:EXCHANGEINSTRUMENTID` - 1 NSECM, 2 NSEFO, 3 NSECD, 4 NSECO, 11 BSECM, 12 BSEFO, 13 BSECD, 21 NCDEX, 51 MCXFO | `1:2885` |
| groww | `EXCHANGE|SEGMENT|EXCHANGE_TOKEN` - `NSE` or `BSE`, `CASH` or `FNO`; an index by name | `NSE|CASH|2885` |
| kotak | `EXCHANGE|TOKEN` with lowercase segments - `nse_cm`, `bse_cm`, `nse_fo`, `bse_fo`, `cde_fo`, `nse_com`, `bse_cd`, `bse_co`, `mcx_fo` - and the `pSymbol` | `nse_cm|11536` |
| stoxkart | `EXCHANGE:TOKEN` - `NSE`, `NFO`, `BSE`, `MCX`; the script refuses `NSECD`, `BSECD`, `BFO` and `NCDEX`, whose broadcast segments are unconfirmed | `NSE:2885` |

Groww's feed has no subjects for commodities, so `COMMODITY` members are skipped. A feed with nothing to
subscribe to exits 2, which its unit does not restart.

### Stoxkart's quote feed

Stoxkart documents a binary quote websocket at `ws://inmob.stoxkart.com:7763`, which could not be reached
on 2026-09-15. `bin/stoxkart/quotes` instead streams from `wss://broadcasting-v2.stoxkart.com/` on port
443, the feed Stoxkart's own trading website uses. The feed takes no login: the token field of the
connection header is left blank, exactly as the website sends it. It is not documented for API users, so
Stoxkart may change it without notice, and the REST poller it replaced is kept in git history as a
fallback.

The protocol is Stoxkart's little-endian binary broadcast format. Every request starts with an 83-byte
header of a request code, the message length, a 30-byte client name and a blank 50-byte token. The script
sends the connection request (code 10), then for each instrument a trade subscription (code 12) and a
depth subscription (code 23), each 129 bytes long. Every answer is a run of packets, and each packet
starts with an 11-byte header of segment, scrip id, a second id, length and packet code. The script reads
these packets and skips the rest:

| Code | Packet | Fields used |
| --- | --- | --- |
| 1 | trade | last price, last quantity, volume, average price, open interest, last trade time, last update time |
| 2 | depth | five levels of bid and ask quantity, orders and price |
| 3 | OHLC | open, high and low |
| 6 | top of book | total quantity offered and total quantity bid |
| 32 | previous close | the previous session's close |

The script sends the text `ping` every five seconds and answers Stoxkart's with `pong`. A socket that is
silent for 30 seconds, or that sends the text `reconnect`, is closed and opened again, with a backoff from
1 to 60 seconds between failed connections. Stoxkart sends an instrument's packets together in one frame,
so the script writes one tick per instrument per frame, and only when the tick has changed. It takes
`--tokens` as its only option, and no `--per-socket`.

The script accepts four exchanges, whose broadcast segments are NSE 1, NFO 2, BSE 4 and MCX 5. It refuses
`NSECD`, `BSECD`, `BFO` and `NCDEX` instruments, because no trade packet was seen for them on 2026-09-15
and their segment numbers are unconfirmed.

The tick's fields that need more than a copy are these:

| Field | How it is made |
| --- | --- |
| `buy_quantity`, `sell_quantity` | The total quantity bid and offered, from the top of book packet |
| `ohlc.close` | The previous close packet |
| `change` | The percentage change of the last price against the previous close |
| `last_trade_time` | The trade packet's last trade time plus 315532800, because Stoxkart counts seconds from 1980-01-01 UTC; null when 0 |
| `exchange_timestamp` | The trade packet's last update time plus 315532800 less 19800, because it counts India wall-clock seconds from 1980; null on MCX, where Stoxkart sends 0 |
| prices | 32-bit floats in rupees, rounded to four decimal places |

A tick's `instrument_token` is `EXCHANGE:TOKEN`, and its `id` is `EXCHANGE:SYMBOL` from
`stoxkart:instruments:master`. A future or option is named by its `symbol_description` only when that
begins with its symbol, is longer than it, has no space and contains a digit, as in `NFO:NIFTY26SEPFUT`.
Any other contract is named from its symbol, expiry as `DDMONYY`, strike and `CE`, `PE` or `FUT`, as in
`MCX:CRUDEOIL21SEP26FUT`, `MCX:GOLD05OCT26FUT` and `MCX:COPPER30SEP26FUT`. Earlier on 2026-09-15 the MCX
GOLD, SILVER, COPPER and ZINC futures were stored under names such as `MCX:GOLD 995` and `MCX:COPPER`, and
those `stoxkart.ticks` rows were renamed by token. The subscription set was seeded on 2026-09-15 with the
same 15 instruments as Zerodha's.

On 2026-09-15 the feed was compared with Zerodha's ticks at the same moment. TCS, RELIANCE, HDFCBANK and
CRUDEOIL SEP matched on last price, volume, average price, OHLC and previous close, and RELIANCE, HDFCBANK
and CRUDEOIL matched on total bid and offered quantity and on the first depth level. CRUDEOIL's open
interest read 15634 at both, in MCX lots, the last trade time matched to the second, and the NSE exchange
time matched for TCS and RELIANCE.

### Order updates

`order_updates` holds its own connection, subscribes to no instruments, and merges each update into
`<broker>:orders:orders` as described above. Fyers, Kotak and Wisdom Capital also send position updates,
and Groww derivatives position updates, which are merged into `<broker>:portfolio:positions`. Every
update is also appended to a stream, so the history the hashes overwrite is kept:

| Stream | Field | Cap | Drained by |
| --- | --- | --- | --- |
| `<broker>:order-updates:stream` | `update` | about 20,000 | `persist_orders` |
| `<broker>:positions_updates:stream` | `position` | about 20,000 | `persist_positions` |

Updates arrive only when an order or position changes, so a quiet socket is not a broken one.

### Stoxkart's order socket

Stoxkart's API documentation offers only a Postback URL for order status, which would need a public web
server. `bin/stoxkart/order_updates` uses the order socket Stoxkart's trading website uses instead, and
that socket accepted the API app's own session on 2026-09-15. The script connects in three steps:

1. It sends `POST https://openapi-v2.stoxkart.com/websocket/authenticate` with the headers `x-client-id`
   (the `ucc_code` setting), `x-access-token` (the API access token), `x-platform: api` and `x-api-key`.
   Stoxkart answers "Authentication successful, server ready to accept WS" with a `data.RequestId`. The
   same token with `x-platform: web` is refused with `AuthorizationError`, so this is access for the API
   platform rather than the website's.
2. It opens `wss://openapi-v2.stoxkart.com/websocket/v2/connect?x-client-id=<client>&x-platform=api&RequestId=<id>`.
3. It sends `{"type":"heartbeat"}` on connecting and every 30 seconds after. Updates arrive as JSON.

Stoxkart keeps one order socket per client. A new connection closes the older one with a close reason
containing `new incoming connection`, so the script and a logged-in Stoxkart website or app knock each
other off. When that happens the script waits five minutes before reclaiming the socket.

The first updates arrived on 2026-09-15. Three NSE KWIL orders sent at 15:40 IST were rejected because
the market had closed, and two after-market KWIL orders were placed and then cancelled. The socket sent
an update within a second of each rejection and each cancellation, but sent nothing when the two
after-market orders were placed, so only `bin/stoxkart/orders` recorded those until they were cancelled.
Every value in an update was a string, and an update carried these fields:

- `client_id`, `user_id`, `order_id`, `exch_order_id` and `order_timestamp`, which was blank
- `variety`, `exchange`, `trading_symbol`, `symbol`, `token`, `segment` and `lot_size`
- `order_type`, `transaction_type`, `validity` and `product`
- `quantity`, `disclose_quantity`, `disclose_quantity_remaining`, `traded_quantity` and `pending_quantity`
- `price` and `trigger_price`
- `order_status` and `reason`
- `expiry_date`, `strike_price` and `option_type`

The cancellation updates said `variety: NORMAL` for the after-market orders, which is why the order
entries carry their own `variety`, as [Orders and positions](#orders-and-positions) describes. Updates
for an open, partly filled or filled order have not been seen, so the script still reads fallbacks for
some fields, such as `status` or `order_status` and `action` or `transaction_type`, and logs every
message at INFO so that the first such update shows its shape in the journal. An update carrying an `order_id` is merged into `stoxkart:orders:orders` with source `websocket`
and appended to `stoxkart:order-updates:stream` as `{"timestamp", "order": <normalized order>, "data": <the update>}`.
Unlike the other brokers' streams, the entry carries the normalized `order`, which
`bin/unified/order_updates` uses as it is.

## Persisters

`persist_ticks`, `persist_orders` and `persist_positions` read their stream as the consumer group
`persist` and write to the broker's hypertable with COPY, a batch at a time. Each applies its broker's
`<NNN>_<broker>_streams.sql` in `stock_brokers/instruments/ticks/utilities/sql/ddl` when it starts - `010`
Zerodha through `100` Stoxkart, holding that broker's `ticks`, `order_updates` and, where it streams
them, `positions` - so a new database needs no separate step, and a start that cannot apply it exits 1. Each takes `--batch-size` and `--flush-interval`, and `persist_ticks` writes a batch when it
holds `--batch-size` ticks or has waited `--flush-interval` seconds, whichever comes first.

| Script | Stream | Table |
| --- | --- | --- |
| `persist_ticks` | `<broker>:quotes:stream` | `<broker>.ticks` |
| `persist_orders` | `<broker>:order-updates:stream` | `<broker>.order_updates`, one row per transition of an order |
| `persist_positions` | `<broker>:positions_updates:stream` | `<broker>.positions`, one row per snapshot of a position |

An entry is acknowledged only after the batch holding it is committed, and pending entries are read first
at the next start, so nothing is lost across a crash - but a batch committed just before one can be
written twice. The one loss is the stream cap: entries trimmed while a persister is stopped are gone, and
are counted as skipped. Run one instance of each. A database or Redis that cannot be reached is retried
with backoff. The consumer groups are separate from the `unified` group the unified scripts read with, so
neither disturbs the other.

## Instrument masters

`instruments` downloads the broker's instrument file once and stores it twice. The table write is the
ingester's: cleaned columns, placeholder and duplicate rows dropped, `download_date` added, appended to
`<broker>.instruments`. A date already stored is skipped unless `--bootstrap` replaces it, and a row count
more than ten percent off the earlier days' average is reported.

In Redis, `<broker>:instruments:master` is a hash of one field per instrument, each value the row as a
JSON array, and `<broker>:instruments:meta` is a JSON object with `download_date`, `rows`, `columns` (the
order the arrays follow), `source_last_modified` and `written_at`. The hash is built under `:staging` and
swapped in, so a reader sees the previous complete hash or the new one. The field is the broker's natural
key: `738561` at Zerodha, `NSE:E:2885` at Dhan and INDmoney, `NSE:RELIANCE-EQ` at Flattrade and Shoonya,
`NSE:SBIN-EQ` at Fyers, `NSECM:2885` at Wisdom Capital, `NSE:CASH:RELIANCE` at Groww, `nse_cm:TCS-EQ` at
Kotak and `NSE:2885` at Stoxkart.

The snapshot can only ever be today's, since the brokers publish no other. Mapping the snapshots into
unified instruments is `bin/unified/map_instruments`; see [Unified scripts](unified-scripts.md).

## Historical prices

```bash
bin/zerodha/historical_prices --seed            # register every instrument and interval, then work
bin/zerodha/historical_prices                   # work the queue until stopped or drained
bin/zerodha/historical_prices --seed-only       # register new series and exit
bin/zerodha/historical_prices --status          # how far it has got
bin/zerodha/historical_prices --deadline-seconds 21600
```

Seeding reads the latest rows of `<broker>.instruments` and registers one row per instrument and interval
in `<broker>.price_history_progress`, leaving existing rows alone. The queue is worked in priority order
and each window is upserted into `<broker>.price_history` together with its progress, in one transaction,
so stopping costs at most the request in flight. A refused session is logged in once and the window
retried. See [Price history](price-history.md) for the queue itself.

The queue is not locked between processes: two workers on one broker's progress table claim the same
series and share the broker's rate limit, so run one. Exit 0 is stopped, drained
or out of time; 1 is a session that could not be restored or a broker that refused this client; 2 is a
failed first login, which the unit does not restart - the morning login timer is the remedy.

## Running them under systemd

Each broker's units live in `services/<broker>/`:

| Unit | Type | What it does |
| --- | --- | --- |
| `<broker>@.service` | template | Runs one long-lived script: `zerodha@quotes` runs `bin/zerodha/quotes`. `Restart=always` after 15 s, never giving up, except on exit 2 |
| `<broker>-login.service` | oneshot | Runs `login`, retried on failure after two minutes, three attempts an hour |
| `<broker>-login.timer` | timer | 08:15 IST Monday to Friday, with up to 30 minutes of random delay |
| `<broker>-historical-prices.service` | service | Runs `historical_prices`, restarted ten minutes after it exits, at low CPU and idle IO priority |
| `<broker>.target` | target | Everything above; stopping it stops them all |

Nothing needs restarting after the morning login: every script reads the current token on each connect
and request, so the login only has to happen before the market opens. The 30 minutes of jitter keeps ten
headless-browser and TOTP logins from firing in the same second and still lands each before 09:00. A
machine that was off at 08:15 needs no catch-up, since the first script refused a token logs in then.

To install a broker, link its units and enable the target, the login timer and the scripts. The commands
are in each target file's comments:

```bash
systemctl --user link ~/Projects/unified_broker_interface/services/zerodha/*
systemctl --user daemon-reload
systemctl --user enable --now zerodha.target zerodha-login.timer \
    zerodha@quotes.service zerodha@order_updates.service zerodha@persist_ticks.service \
    zerodha@persist_orders.service zerodha@orders.service zerodha@trades.service \
    zerodha@positions.service zerodha@holdings.service zerodha@funds.service \
    zerodha@user-profile.service zerodha-historical-prices.service
```

The other targets list the same set adjusted for the matrix above: `@persist_positions` for Fyers, Groww,
Kotak and Wisdom Capital, no `@user-profile` for Kotak, and no historical prices service for Groww,
Kotak or Stoxkart. `stoxkart.target` enables `@quotes`, `@order_updates`, `@persist_ticks`,
`@persist_orders`, `@orders`, `@trades`, `@positions`, `@holdings`, `@funds` and `@user-profile`, plus
`stoxkart-login.timer`. `bin/<broker>/instruments` has no unit here; it runs from `unified-instruments.service`.

!!! warning "Flattrade leaves `order_updates` out"

    Flattrade permits one websocket per session and `flattrade@quotes` holds it, so `flattrade.target`
    does not enable `flattrade@order_updates.service`: running both would knock one of them off. Flattrade's
    orders still reach `flattrade:orders:orders` through the poller. See
    [Known issues](../contributing/known-issues.md).

Fyers' `fyers@.service` and `fyers-historical-prices.service` wait a random 0 to 30 seconds before
starting, because a whole target starting at once sent more requests than Fyers accepts, and a login one
script then attempted spoiled another's auth code.

## Looking at it

```bash
systemctl --user list-units 'zerodha*'
journalctl --user -u zerodha@orders -f
journalctl --user -u zerodha-login --since today
redis-cli GET zerodha:session:status
redis-cli GET zerodha:orders:orders:polled_at
redis-cli XINFO GROUPS zerodha:quotes:stream        # the persist and unified groups' lag
```
