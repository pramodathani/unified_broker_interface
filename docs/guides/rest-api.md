# REST API

The `unified_broker_interface` package is a Flask application that puts one HTTP interface in
front of the project. A client logs in with an api key and secret, receives an access token, and
sends that token with every other request.

Six groups of endpoints are served today: the session, the user, broker and exchange details, the
[instruments](#instruments), the [portfolio](#portfolio) - funds, holdings and positions - and
[orders](#orders) - today's order book and trade book, [placing an order](#placing-an-order) and
[cancelling an order](#cancelling-an-order). The API places and cancels orders but does not modify them.

## Running it

```bash
rest-api                 # gunicorn, two workers of four threads, on 127.0.0.1:8080
rest-api --workers 4 --threads 8
rest-api --dev           # Flask's development server, for local debugging
```

The workers are threaded, so a long stream or a slow broker quote holds one thread rather than a whole
worker, and is not cut off by gunicorn's timeout for a hung worker. The address and the token lifetime
come from the environment. All seven variables are optional, and each is read once when a worker starts.

| Variable | Default | Meaning |
| --- | --- | --- |
| `UNIFIED_BROKER_INTERFACE_API_HOST` | `127.0.0.1` | Address to bind |
| `UNIFIED_BROKER_INTERFACE_API_PORT` | `8080` | Port to bind |
| `UNIFIED_BROKER_INTERFACE_API_TOKEN_TTL_SECONDS` | `86400` | How long an access token is accepted |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS` | empty | Comma-separated broker names that `POST /api/orders/place` never sends to, such as `kotak,groww` |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR` | `round_robin` | How `POST /api/orders/place` orders the brokers: `round_robin` or `fixed_priority`; any other name stops the API from starting |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS` | empty | Comma-separated broker names whose order connection each worker keeps warm, such as `zerodha,dhan`; see [Broker connections](#broker-connections). Unknown names are logged and ignored |
| `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY` | empty | For `fixed_priority`, comma-separated broker names in order of preference, such as `zerodha,kotak`; brokers not named follow in the usual order |

## Endpoints

| Method | Path | Authenticates with | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/` | nothing | A greeting, to tell the API is up |
| `POST` | `/api/session/connect` | `api-key` and `api-secret` headers | `{"access-token": …, "expires_at": …}` |
| `DELETE` | `/api/session/disconnect` | `access-token` header | `{"status": "disconnected"}` |
| `GET` | `/api/session/status` | `access-token` header | `{"status": "connected", "expires_at": …}` |
| `GET` | `/api/users/details` | `access-token` header | `{"user_details": […], "broker_profiles": {…}}`: every document in `user_details` (from its Redis copy `unified:details:users`, MongoDB when there is none), and each broker's profile from the Redis key `unified:user:details` (null when that key is missing) |
| `GET` | `/api/brokers/details` | `access-token` header | Every document in `broker_details`, from its Redis copy `unified:details:brokers` (MongoDB when there is none) |
| `GET` | `/api/exchanges/details` | `access-token` header | Every document in `exchange_details`, from its Redis copy `unified:details:exchanges` (MongoDB when there is none) |
| `GET` | `/api/portfolio/funds` | `access-token` header | The account's funds, summed across every broker, from `unified:portfolio:funds` |
| `GET` | `/api/portfolio/holdings` | `access-token` header | The account's holdings, merged across every broker and priced, from `unified:portfolio:holdings` |
| `GET` | `/api/portfolio/positions` | `access-token` header | The account's open positions, net and day, merged across every broker, from `unified:portfolio:positions` |
| `GET` | `/api/orders/details` | `access-token` header | Today's orders at every broker, from `unified:orders:orders` |
| `GET` | `/api/orders/trades` | `access-token` header | Today's trades at every broker, from `unified:orders:trades` |
| `POST` | `/api/orders/place` | `access-token` header | Places one order at the broker the configured selector chooses, see [Placing an order](#placing-an-order) |
| `DELETE` | `/api/orders/cancel` | `access-token` header | Cancels one order at the broker that holds it, see [Cancelling an order](#cancelling-an-order) |

Errors come back as `{"error": "…"}`. A refused token is `401`, with a message saying whether it
was missing, not the token in force, or expired. A detail collection with nothing in it is `404`.

```bash
TOKEN=$(curl -s -X POST localhost:8080/api/session/connect \
          -H "api-key: $API_KEY" -H "api-secret: $API_SECRET" | jq -r '."access-token"')

curl -s localhost:8080/api/brokers/details -H "access-token: $TOKEN"
curl -s -X DELETE localhost:8080/api/session/disconnect -H "access-token: $TOKEN"
```

## The session

The key and secret a client must present are the `api_key` and `api_secret` of the
`unified_broker_interface` document in the MongoDB `settings` collection, beside the brokers'
credentials. Both are compared in constant time and never logged.

```json
{ "broker_name": "unified_broker_interface", "api_key": "…", "api_secret": "…" }
```

A successful connect mints a UUID and stores it the way a broker login is stored: in `last_login`
under the same `broker_name`, MongoDB first and then the Redis `last_login` hash. Every request
reads the token from Redis, falling back to MongoDB, so a token issued by one gunicorn worker is
accepted by all of them.

```json
{
  "broker_name": "unified_broker_interface",
  "access_token": "5b0c9d0e-8f7a-4c35-9a53-2f4f0f4f7a61",
  "last_login": "2026-09-13 16:02:11.402913",
  "expires_at": "2026-09-14 16:02:11.402913"
}
```

!!! warning "One session at a time"

    There is one token for the whole application. Each connect replaces it, so a second client
    connecting ends the first client's session, and a disconnect ends it for everyone.

## The detail collections

The three detail collections are loaded from MongoDB Compass exports:

```bash
import-api-details /path/to/exports             # upsert exchanges and brokers, load users if empty
import-api-details /path/to/exports --replace   # also reload user_details over what is there
```

| Collection | Keyed by | Corrections on the way in |
| --- | --- | --- |
| `exchange_details` | `exchange` (`nse`, `bse`, `mcx`, `ncdex`) | `exchange` added from the lowercased `short_name` |
| `broker_details` | `broker_name` (`zerodha`, `kotak`, …) | The misspelt `borker_name` display name moves to `name`; `broker_name` becomes the project's broker code |
| `user_details` | nothing | None; loaded only into an empty collection unless `--replace` |

Exchanges and brokers are upserted under a unique index on their key, so the import is safe to
re-run. An unrecognised broker display name stops the import before anything is written.

MongoDB is the store of record, and `bin/unified/details` copies the three collections into Redis every
minute - `unified:details:users`, `unified:details:brokers` and `unified:details:exchanges`, each a JSON
array of the documents - which is what the detail endpoints serve. So an import reaches the API within a
minute, and when a copy is missing the endpoints read MongoDB instead.

### Trading hours and holidays

After the exports, the same command copies each exchange's trading hours, holidays and special
sessions into its `exchange_details` document, so `GET /api/exchanges/details` returns them. They are
copied, not linked: a change to the sources reaches the API when the copy is run again, and its Redis
copy within the minute after.

```bash
import-api-details --calendars-only             # re-copy after a calendar file changes
```

| Field | Copied from |
| --- | --- |
| `holidays` | `stock_brokers/instruments/ticks/utilities/calendars/<year>.yaml`, every year merged, per calendar |
| `special_sessions` | The same files, narrowed to the calendars the exchange has |
| `trading_hours` | `TRADING_HOURS` in [`exchange_calendar`][unified_broker_interface.utilities.exchange_calendar] |

```json
{
  "exchange": "mcx",
  "trading_hours": {
    "timezone": "Asia/Kolkata",
    "commodity": {
      "sessions": [
        {"name": "morning", "opens": "09:00", "closes": "17:00"},
        {"name": "evening", "opens": "17:00", "closes": "23:30", "closes_during_us_standard_time": "23:55"}
      ]
    }
  },
  "holidays": {
    "commodity": [{"date": "2026-01-01", "closed": "evening", "name": "New Year Day"}]
  },
  "special_sessions": [
    {"date": "2026-11-08", "name": "Muhurat trading (timings to be notified)",
     "calendars": ["commodity"], "opens": "09:00", "closes": "23:59:59"}
  ],
  "calendar_years": [2026],
  "calendar_copied_at": "2026-09-13 19:50:02.114210"
}
```

A calendar is the set of segments that close together - `equity` (cash, indices, equity
derivatives), `currency` and `commodity` - and NSE and BSE carry all three while MCX and NCDEX carry
only `commodity`. A holiday's `closed` is `all`, or `morning` or `evening` on a commodity calendar,
whose day splits into two sessions at 17:00.

!!! note "Trading hours are not the tick windows"

    `stock_brokers/instruments/ticks/utilities/sessions.py` also defines per-segment times, but those
    are the wider windows ticks are accepted in - opening at 09:00 for everything and closing after the
    session. The copied `trading_hours` are the sessions' actual hours.

!!! danger "`user_details` holds identity and bank data"

    PAN, Aadhaar and bank account numbers. The exports are read from wherever they are and are
    never to be copied into the repository.

See [`unified_broker_interface.utilities.tokens`][unified_broker_interface.utilities.tokens] and
[`unified_broker_interface.utilities.import_details`][unified_broker_interface.utilities.import_details]
for the details.

## Instruments

Everything under `/api/instruments` takes the `access-token` header and answers `GET`.

| Path | Parameters | Returns | Answered from |
| --- | --- | --- | --- |
| `/segments` | none | Every segment mapped today, with its shape, identity fields and instrument count | Redis |
| `/master` | `exchange`, `segment` (either may be `all`), `date` | **Streamed** JSON array of identities, in segment, name, expiry, strike order; `X-Mapping-Date` header | Redis |
| `/search` | `exchange`, `segment`, `q`, `date`, `limit` (50, at most 200) | `{mapping_date, instruments}`: exact name matches, then prefixes, then substrings | Redis |
| `/details` | an instrument, `date` | Identity, `mapping_date`, seen dates, the instrument's `lot_size` and `tick_size`, and `carried_by` each broker's token, order symbol, lot and tick size | Redis |
| `/ltp` | an instrument | Identity, `last_price`, `last_trade_time`, `received_at`, `source` | Quote cache or broker |
| `/ohlc` | an instrument | The above with `ohlc`, `previous_close`, `change_percent` | Quote cache or broker |
| `/quote` | an instrument | The whole [unified quote](../architecture/contracts.md#the-unified-quote), depth included, with `source` | Quote cache or broker |
| `/prices` | an instrument, `interval`, `from` and `to` or `days`, `adjusted` (true), `known_as_of` | `{identity, interval, adjustable, price_basis, columns, candles}` | `unified.price_history` |
| `/ticks` | an instrument, `start`, `end`, `adjusted` (true) | **Streamed** JSON array of stored ticks, `start <= time < end`, oldest first; `X-Price-Basis` header | `unified.ticks` |

**An instrument** is either `instrument_id`, or `exchange`, `segment` and the identity fields its shape
needs: `symbol` for a security; `underlying_symbol` and `expiry_date` for a future; those and
`strike_price` and `option_type` for an option. Names are matched case-insensitively. `segment` may be
the stored value (`nse_equities`) or the bare name (`equities`).

**Lot and tick size.** The top-level `lot_size` and `tick_size` in `/details` are the ones to use for the
instrument itself. `lot_size` is an integer count of underlying units per lot, decided exactly as the
[unified quote](../architecture/contracts.md#the-unified-quote) decides it: 1 for a security, Groww's figure
on MCX, and the brokers' majority elsewhere. `tick_size` is a string in rupees, the value most brokers
agree on. Either is null when the brokers tie or none sends one. The entries in `carried_by` are each
broker's own handle and are not interchangeable: on MCX, Dhan, Fyers, Wisdom Capital and Zerodha give a
lot size of 1 (one lot), Flattrade, Kotak, Shoonya and Stoxkart give the lot in the exchange's physical
trading unit, and Groww gives it in quotation units. An order's quantity is checked against the lot size
of the broker it goes to.

```bash
curl -s "localhost:8080/api/instruments/search?exchange=nse&segment=equities&q=RELIANCE" -H "access-token: $TOKEN"
curl -s "localhost:8080/api/instruments/quote?exchange=nse&segment=equities&symbol=INFY" -H "access-token: $TOKEN"
curl -s "localhost:8080/api/instruments/details?exchange=nse&segment=equity_index_options&underlying_symbol=NIFTY&expiry_date=2026-09-29&strike_price=25000&option_type=CE" -H "access-token: $TOKEN"
curl -s "localhost:8080/api/instruments/prices?instrument_id=3f92570a-9924-5bf5-9f9d-e006cd9f4202&interval=day&days=365" -H "access-token: $TOKEN"
curl -s "localhost:8080/api/instruments/ticks?instrument_id=$ID&start=2026-09-11%2009:15&end=2026-09-11%2015:30" -H "access-token: $TOKEN"
```

`start` and `end` take a date, a date and time, or ISO 8601; without an offset they are India time. A
stream's status is settled before it starts: a bad parameter or an unknown instrument is an ordinary
`400` or `404`. A failure part way through a stream is logged and ends the array early.

### Lookups come from the mapping cache

`/segments`, `/master`, `/search` and `/details` read the Redis tier of the
[instrument mapping cache](instrument-mapping.md), kept under `unified:catalogue:` for the unified tables
`unified.instruments` and `unified.broker_mappings`, and run no database query. `bin/unified/map_instruments`
warms it each day after mapping, from those tables: besides the identity and order handle hashes, a catalogue
per segment - a sorted set of every instrument in name, expiry, strike order and a set of its distinct names -
plus every instrument's seen dates and a count per segment. See
[Redis keys](../architecture/redis-keys.md#the-rest-apis-catalogue).

Postgres is read, and a line logged, in three cases only:

- a `date` before today's mapping date, which the cache does not hold by design;
- a cache that has not been warmed for today - the catalogue counts are written last, so their absence
  is how that is seen;
- `/prices` or `/ticks` for an instrument no longer mapped, such as an expired contract, whose history
  is still wanted.

!!! note "A cache warmed before the catalogue existed"

    Until the next warm, today's catalogue keys are missing and the lookups fall back to Postgres. Run
    `bin/unified/map_instruments --cache-only --date <mapping date>` once to write them now.

### Live quotes

`/ltp`, `/ohlc` and `/quote` serve the unified quote cache - `unified:quotes:live`, which `bin/unified/quotes`
writes from every broker's quote feed, or `unified:quotes:fetched`, quotes this API fetched earlier - whichever
arrived later, when it is not stale and either:

- it arrived in the last five minutes, or
- the instrument's trading window has closed since it arrived and not reopened.

Most instruments trade rarely, so a five minute old quote is still the market, and after the close the
last quote stands until the next session opens - holidays included. Otherwise the API asks a broker
that carries the instrument, in the unified quotes' broker priority order, and `source` is `broker`.

A fetched quote is turned into a feed tick and normalized by the same `TickNormalizer` and built by the
same document shape as a streamed one, so the two are the same shape and mean the same thing. It is
kept for two days in `unified:quotes:fetched`, which answers the next request, and never written into
`unified:quotes:live`.

The REST quote modules live in `unified_broker_interface/utilities/broker_quotes/`, one per broker, each
turning its broker's response into exactly the tick that broker's market feed would publish. In
service, in the order they are tried:

| Broker | Quotes | Not quoted |
| --- | --- | --- |
| Zerodha | NSE, BSE, MCX, currency | NCDEX |
| Dhan | NSE, BSE, MCX, indices, currency | NSE commodity options, NCDEX |
| Kotak | NSE, BSE, MCX, the four NSE indices Kotak lists | SENSEX and other BSE indices, NCDEX |
| Flattrade | NSE, BSE, MCX, currency | NCDEX |
| Shoonya | NSE, BSE, MCX, currency | NCDEX (its stored tokens are trading symbols) |
| INDmoney | NSE cash, NSE and BSE indices and equity derivatives | BSE cash (answered with the NSE listing's quote), MCX, currency |

An instrument none of them carries answers `503` when the cache cannot.

!!! warning "Fyers and Groww are not in service, and Wisdom Capital has no module"

    Fyers' and Groww's modules exist but are not registered. Fyers' field mapping could not be verified,
    because its request limit was used up by the candle downloader. Groww's account is not entitled to live
    data. Wisdom Capital has no quote module: its quotes need the market data session,
    and XTS issues one per application key, which `bin/wisdom_capital/quotes` and
    `bin/wisdom_capital/historical_prices` share.

A broker client in the API is built without its constructor's probe, and the API never logs a broker in:
logins belong to each broker's `<broker>-login.service`. When a broker refuses the session, the API retries
once only if another process has already stored a newer session; otherwise it starts that broker's login unit
without waiting and tries the next broker. systemd runs one login at a time per broker, and each worker asks at
most once every five minutes.

### Adjusted prices

Splits, bonuses and demergers apply only to **equities, exchange traded funds and investment trusts**.
Those are stored unadjusted, and `adjusted=true` (the default) applies the confirmed factors on read:
`/prices` through `unified.adjusted_bars()`, where `known_as_of` restricts them to the factors known
by a date, and `/ticks` through `unified.ticks_adjusted`. `adjusted=false` reads the raw rows. Both are kept
by `bin/unified/historical_prices`, and the ticks by `bin/unified/persist_ticks`.

Everything else - futures and options, including those on an adjustable equity, indices, bonds,
currencies, commodities and mutual funds - is stored as the broker served it and returned the same
whatever `adjusted` says. Every answer states which it is:

| `adjustable` | `price_basis` | Meaning |
| --- | --- | --- |
| `true` | `adjusted` | Factors applied; each candle carries its `price_factor` |
| `true` | `unadjusted` | Raw prices, as traded |
| `false` | `as_served` | Nothing to adjust |

`interval` is any interval `bin/unified/historical_prices load` accepts; `day` is loaded for every instrument,
intraday intervals only where they have been loaded by hand. An intraday range may span at most 366 days.

## Portfolio

Everything under `/api/portfolio` takes the `access-token` header and answers `GET`.

| Path | Parameters | Returns | Answered from |
| --- | --- | --- | --- |
| `/funds` | none | The account's funds summed across every broker, and how each broker's data was read | `unified:portfolio:funds`, written by `bin/unified/funds` every half second |
| `/holdings` | none | The account's holdings, one row per instrument across every broker, priced, and how each broker's data was read | `unified:portfolio:holdings`, written by `bin/unified/holdings` every minute; prices from `unified:quotes:live` |
| `/positions` | none | The account's open positions, net and day, one row per instrument and product across every broker, and how each broker's data was read | `unified:portfolio:positions`, written by `bin/unified/positions` every half second; prices from `unified:quotes:live` |

```bash
curl -s localhost:8080/api/portfolio/funds -H "access-token: $TOKEN"
curl -s localhost:8080/api/portfolio/holdings -H "access-token: $TOKEN"
curl -s localhost:8080/api/portfolio/positions -H "access-token: $TOKEN"
```

### Funds

The client sees one account rather than a set of brokers: every broker's balances are added into the same
buckets. The brokers are all ten, each read from its own `bin/<broker>/funds` poller.

```json
{
  "summary": {
    "total_balance": 125000.0, "available_balance": 125000.0, "cash_balance": 0.0,
    "collateral_value": 0.0, "adhoc_credit": 0.0, "margin_utilized": 0.0, "withdrawable_balance": 0.0
  },
  "pnl": { "realized": 0.0, "unrealized": 0.0 },
  "margin_breakdown": { "span_margin": 0.0, "exposure_margin": 0.0, "other_margin": 0.0 },
  "cash_movement": { "pay_in_today": 0.0, "pay_out_today": 0.0, "uncleared_funds": 0.0, "pending_withdrawal": 0.0 },
  "segments": {
    "equity": { "available_balance": 125000.0, "margin_utilized": 0.0, "span_margin": 0.0, "exposure_margin": 0.0 },
    "commodity": { "available_balance": 0.0, "margin_utilized": 0.0, "span_margin": 0.0, "exposure_margin": 0.0 }
  },
  "brokers": [ { "broker": "zerodha", "status": "ok" } ],
  "as_of": "2026-09-13T22:07:05"
}
```

- `available_balance` is what can back a new order; `margin_utilized` is what open positions already block.
- `total_balance` is their sum. No broker reports a total, and several state only the available
  balance without its cash, collateral and credit parts, so those parts do not add back up to it.
- A field a broker does not report adds nothing, so a zero can mean either "none" or "not reported".
- `segments` holds only what brokers report per segment, so the segments do not add up to `summary`.
- Figures are rounded to paise. `as_of` is the server's local time without an offset, which is India
  time on this machine.

**Nothing is asked at request time.** Each broker's own scripts poll it and keep its answer in Redis -
`bin/<broker>/funds` as `<broker>:portfolio:funds` - and `bin/unified/funds` combines them into this document
every half second, which the route returns as it stands. A request therefore costs one Redis read, however many
brokers there are, and the figures are at most a poll behind the brokers. Logging in again after a refused
session is the broker scripts' job, not the request's.

**`brokers` says how each broker's data was read.** A broker without data contributes nothing, and it is listed
rather than dropped, so it is never mistaken for a broker holding no money:

| `status` | Meaning |
| --- | --- |
| `ok` | Written by its broker script within the last minute, and included |
| `stale` | Last written more than a minute ago - its script has probably stopped - and still included |
| `missing` | Nothing stored: its script has not run today |
| `unreadable` | Something is stored but it could not be read |

**When the document is not served.** A missing or unreadable document - `bin/unified/funds` is not running - is
`503`. So is a document whose `as_of` is more than thirty seconds old, with its `as_of` and `brokers`, so an old
balance is never passed off as today's. A document in which no broker is `ok` or `stale` is `502` with an `error`
and the `brokers` list. The same rules hold for holdings (five minutes, since it is written every minute),
positions, orders and trades.

Each broker's `bin/<broker>/funds` script reads its own response into these buckets. Where a broker states what can back a new order, that figure is the available balance; where it
does not, the balance is derived as shown.

| Broker | Endpoint | `available_balance` | `segments` |
| --- | --- | --- | --- |
| Zerodha | `GET /user/margins` | `net` of the equity and commodity blocks | equity, commodity |
| Dhan | `GET /v2/fundlimit` | `availabelBalance` (Dhan's spelling) | none |
| Flattrade, Shoonya | `POST …/Limits` | derived: cash + collateral + day cash − margin used | SPAN and exposure, once a segment has activity |
| Fyers | `GET /api/v3/funds` | the "Available Balance" row, equity plus commodity | equity, commodity |
| Groww | `GET /v1/margins/detail/user` | derived: clear cash + collateral available + adhoc margin − net margin used | equity, derivatives, commodity |
| INDmoney | `GET /funds` | derived: start of day balance + pledge received | equity, derivatives, commodity |
| Kotak | `POST {base_url}/quick/user/limits` | `Net` | commodity, derivatives, currency margins |
| Stoxkart | `GET /funds` | `available_limit`; margin used is the absolute `utilized_limit`, which Stoxkart's documentation shows as negative | none |
| Wisdom Capital | `GET /interactive/user/balance` | `netMarginAvailable` | none |

!!! warning "Fyers and Stoxkart"

    Fyers allows an app 200 requests a minute and 100,000 a day, so `bin/fyers/` polls funds every thirty
    seconds, trades every fifteen and orders and positions every five, and its history download is held to
    half a request a second. When Fyers rate limits a poller it pauses five minutes, thirty after a
    Cloudflare ban, and Fyers shows `stale` meanwhile. Stoxkart documents a limit of one request a second
    for funds, trades, orders and positions, so `bin/stoxkart/` polls each of them once a second.

### Holdings

Holdings are served the way funds are - from `unified:portfolio:holdings`, written by `bin/unified/holdings` from
each broker's `<broker>:portfolio:holdings`, with the same `brokers` list and the same `503` and `502` answers - and
combined into one row per instrument. The document is written every minute, so one up to five minutes old is
served.

```json
{
  "holdings": [
    {
      "instrument_id": "3f1c9a52-7d0e-5b8a-9c41-2e6f8d0b7a13",
      "isin": "INE062A01020", "symbol": "SBIN", "exchange": "nse", "segment": "nse_equities",
      "quantity": 20.0, "average_price": 780.5, "invested_value": 15610.0,
      "last_price": 812.35, "current_value": 16247.0,
      "pnl": { "unrealized": 637.0, "day_change": 4.1, "day_change_percentage": 0.51 },
      "collateral_quantity": 0.0
    }
  ],
  "summary": { "holdings_count": 3, "total_investment": 48250.0, "total_current_value": 50110.4, "total_unrealized_pnl": 1860.4 },
  "brokers": [ { "broker": "dhan", "status": "ok" } ],
  "as_of": "2026-09-13T22:32:57"
}
```

**Resolved to an instrument.** A holding's broker token is looked up in the mapping cache among the cash
segments on the exchange the broker names - NSE then BSE when it names none - and the row carries the
instrument's id, symbol, exchange and segment. When a token maps to more than one instrument the cash
segments are taken in order, equities first. Groww sends no token and is looked up by its trading symbol.
A holding nothing resolves keeps the broker's own symbol, with `instrument_id` and `segment` null.

**Merged.** Holdings sharing an ISIN or an instrument id are one row, whichever broker's arrives first, so
Kotak, which sends no ISIN, joins another broker's row once its token resolves, and a stock held on NSE at
one broker and on BSE at another is one row under the first listing. Quantities, invested values and
pledged quantities add up, and `average_price` is the invested value over the quantity.

**Everything held.** A quantity is every bucket a broker reports - settled, bought and not yet settled
(T1), and funded by margin trading - so a stock bought yesterday counts before it settles.

**Priced by the unified quote.** A resolved row's `last_price` is the instrument's unified quote, as
`/api/instruments/ltp` answers it - the quote cache, or a broker's REST quote when the cache is not recent
enough - and `day_change` is measured from that quote's previous close. A row without an instrument, or
whose quote was not had in time, uses the last price a broker sent, or its previous close. A row with
no price at all has `current_value` and `pnl.unrealized` null and is left out of the value and profit
totals, though its cost is in `total_investment`.

| Broker | Endpoint | Instrument from | Quantity |
| --- | --- | --- | --- |
| Zerodha | `GET /portfolio/holdings` | `instrument_token`, `exchange` | `quantity` + `t1_quantity` + `mtf.quantity` |
| Dhan | `GET /v2/holdings` | `securityId`, `exchange` (`ALL`: NSE, then BSE) | `totalQty` |
| Flattrade, Shoonya | `POST …/Holdings` | the first `exch_tsym` listing's token and exchange | `holdqty` + `npoadqty` + `npoadt1qty` |
| Fyers | `GET /api/v3/holdings` | `fyToken`, the `symbol` prefix | `quantity` + `qty_t1` |
| Groww | `GET /v1/holdings/user` | `trading_symbol` on the first tradable exchange | `quantity` |
| INDmoney | `GET /portfolio/holdings` | `security_id`, on NSE | `total_qty` |
| Kotak | `GET {base_url}/portfolio/v1/holdings` | `exchangeIdentifier`, `exchangeSegment` | `quantity` |
| Stoxkart | `GET /portfolio/holdings` | `nse_token` or `bse_token`, whichever `exchange` names, else the other | `quantity` |
| Wisdom Capital | `GET /interactive/portfolio/holdings` | `ExchangeNSEInstrumentId`, else `ExchangeBSEInstrumentId` | `HoldingQuantity` |

!!! warning "Fyers"

    Fyers' holdings fields are its documentation's and have not been read back: its request limit was
    used up by the candle downloader. Funds and holdings share one Fyers pause, since a rate limit or a
    Cloudflare ban is on the address rather than the endpoint.

### Positions

Positions are served the way funds are - from `unified:portfolio:positions`, written every half second by
`bin/unified/positions` from each broker's `<broker>:portfolio:positions`, which its REST poller and, for Fyers,
Groww, Kotak and Wisdom Capital, its position update websocket keep - with the same `brokers` list and the same
`503` and `502` answers, on two bases:

- `net`, every position open now, carried or taken today;
- `day`, today's activity alone, which only Zerodha and Wisdom Capital report.

```json
{
  "net": [
    {
      "instrument_id": "7b0e3be4-a930-5521-986c-acda3c1d7c9b",
      "symbol": "NIFTY", "exchange": "nse", "segment": "nse_equity_index_options",
      "expiry_date": "2026-09-15", "strike_price": 21650.0, "option_type": "CE",
      "product": "carry", "quantity": -75.0,
      "buy": { "quantity": 0.0, "average_price": 0.0, "value": 0.0 },
      "sell": { "quantity": 75.0, "average_price": 100.0, "value": 7500.0 },
      "average_price": 100.0, "last_price": 98.4,
      "pnl": { "realized": 0.0, "unrealized": 120.5, "total": 120.5 },
      "day_change": -2.6, "day_change_percentage": -2.57
    }
  ],
  "day": [],
  "summary": {
    "net": { "count": 1, "realized_pnl": 0.0, "unrealized_pnl": 120.5, "total_pnl": 120.5 },
    "day": { "count": 0, "realized_pnl": 0.0, "unrealized_pnl": 0.0, "total_pnl": 0.0 }
  },
  "brokers": [ { "broker": "zerodha", "status": "ok" } ],
  "as_of": "2026-09-13T22:47:22"
}
```

**Resolved within the venue.** Every broker names where a position trades in its own code - `NFO`,
`NSE_FNO`, `NSEFO`, `nse_fo` - and each says both an exchange and a kind: cash, derivative, currency or
commodity. A token is only unique within one of an exchange's scrip files, so it is resolved among that
kind's segments on that exchange. A derivative carries its `expiry_date`, `strike_price` and `option_type`,
and `symbol` is its underlying. Groww sends no token, so its cash positions resolve by trading symbol, and a
Groww derivative keeps Groww's own symbol, with no id.

**Merged by instrument and product**, or by exchange, symbol and product when unresolved. `quantity` is
signed, positive long and negative short. Buy and sell values add across brokers and the averages are
worked out from them, with `average_price` the bought value less the sold value over the net quantity.

**Profit is the brokers' own.** Only a broker applies a contract's multiplier, so `pnl` is what each broker
reported, summed. Kotak and Groww report none, so their positions add nothing to it. `last_price` and the day
change come from the unified quote, falling back to the broker's price and previous close.

| Broker | Endpoint | Instrument from | Quantity |
| --- | --- | --- | --- |
| Zerodha | `GET /portfolio/positions` | `instrument_token`, `exchange` | `quantity`; `net` and `day` |
| Dhan | `GET /v2/positions` | `securityId`, `exchangeSegment` | `netQty`; values from `buyAvg` and `sellAvg` |
| Flattrade, Shoonya | `POST …/PositionBook` | `token`, `exch` | `netqty`; day and carried forward buys and sells |
| Fyers | `GET /api/v3/positions` | `fyToken`, the `symbol` prefix and `segment` | `netQty` |
| Groww | `GET /v1/positions/user` | `trading_symbol`, `exchange` and `segment` | `quantity`; values from `credit_price` and `debit_price` |
| INDmoney | `GET /portfolio/positions` | `security_id`, `exchange` | `net_qty` |
| Kotak | `GET {base_url}/quick/user/positions` | `tok`, `exSeg` | bought less sold, day and carried forward |
| Stoxkart | `GET /portfolio/positions` | `token`, `exchange` | `net_quantity`; `mark_to_market` read as unrealized profit |
| Wisdom Capital | `GET /interactive/portfolio/positions`, `NetWise` and `DayWise` | `ExchangeInstrumentId`, `ExchangeSegment` | `Quantity`; `net` and `day` |

!!! warning "No position has been read back yet"

    Every account was flat when this was written. Only the empty
    answers were seen live: `[]` from Dhan and INDmoney, `{"net": [], "day": []}` from Zerodha, `{"positions":
    []}` from Groww, `{"positionList": []}` from Wisdom Capital on both bases, Noren's `Not_Ok` "no data",
    and Kotak's `stCode` 5203. The field names inside a row follow each broker's published schema, and
    INDmoney's, which has none, an unconfirmed reading. Check them on a day with an
    open position.

## Orders

Everything under `/api/orders` takes the `access-token` header. The order book and trade book below answer
`GET`, [placing an order](#placing-an-order) is a `POST` and [cancelling an order](#cancelling-an-order) is a
`DELETE`. Nothing modifies an order.

| Path | Parameters | Returns | Answered from |
| --- | --- | --- | --- |
| `/details` | none | Today's orders at every broker, and how each broker's data was read | `unified:orders:orders`, written by `bin/unified/orders` every half second |
| `/trades` | none | Today's trades at every broker, and how each broker's data was read | `unified:orders:trades`, written by `bin/unified/trades` every half second |
| `/place` | a JSON body, below | The broker's answer to one order | one request to the broker whose turn it is |
| `/cancel` | `order_id`, below | The broker's answer to one cancel | one request to the broker whose order book holds the order |

```bash
curl -s localhost:8080/api/orders/details -H "access-token: $TOKEN"
curl -s localhost:8080/api/orders/trades -H "access-token: $TOKEN"
```

Both are served the way the portfolio is, with the same `brokers` list and the same `503` and `502` answers.
Orders come from each broker's `<broker>:orders:orders`, which its order book poller and its order update
websocket both keep, so an order's latest state arrives within a poll or as the broker pushes it. Orders and
trades are not merged: each is one broker's, and `broker` says whose.

### The order book

An order is the [order contract](../architecture/contracts.md#the-order) the broker scripts write, so an
order read here and the update the broker's websocket sent for it mean the same thing: the same fields, the
same [shared vocabulary](../architecture/contracts.md#the-shared-vocabulary), and a `status` of `PENDING`,
`OPEN`, `COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED`. The API answers with `broker` and the order's
`instrument_id`, and without `raw` and `received_at`.

```json
{
  "orders": [
    {
      "broker": "flattrade", "order_id": "26091200000123", "exchange_order_id": "1100000000012345",
      "parent_order_id": null, "instrument_id": "3f1c9a52-7d0e-5b8a-9c41-2e6f8d0b7a13",
      "id": "NSE:SBIN-EQ", "instrument_token": "3045", "tradingsymbol": "SBIN-EQ", "exchange": "NSE",
      "transaction_type": "BUY", "product": "CNC", "order_type": "LIMIT", "validity": "DAY",
      "status": "OPEN", "status_message": null,
      "quantity": 10, "filled_quantity": 0, "pending_quantity": 10, "cancelled_quantity": 0,
      "disclosed_quantity": 0, "price": 805.0, "trigger_price": null, "average_price": null,
      "order_timestamp": "10:12:15 12-09-2026", "exchange_timestamp": null, "tag": null
    }
  ],
  "summary": { "count": 1, "by_status": { "OPEN": 1 }, "filled_value": 0.0 },
  "brokers": [ { "broker": "flattrade", "status": "ok" } ],
  "as_of": "2026-09-13T23:36:42"
}
```

`exchange` is the broker's own exchange or segment code, as the order contract has it - `NSE`, `NSE_EQ`,
`NSECM`, `nse_cm`. Timestamps are passed through as each broker writes them, so orders are sorted by broker
and then by time. `filled_value` is the filled quantity times the average price, over every order.

### The trade book

A trade is one fill, in the same vocabulary:

```json
{
  "broker": "zerodha", "trade_id": "t1", "order_id": "250913000123", "exchange_order_id": "1100000012345",
  "exchange_trade_id": null, "instrument_id": "3f1c9a52-7d0e-5b8a-9c41-2e6f8d0b7a13",
  "instrument_token": "779521", "tradingsymbol": "SBIN", "exchange": "NSE",
  "transaction_type": "BUY", "product": "CNC", "quantity": 1, "price": 805.0, "value": 805.0,
  "trade_timestamp": "2026-09-13 09:15:01", "exchange_timestamp": null
}
```

A trade's `order_id` is its order's, so fills link to orders by `broker` and `order_id`. The summary is
`count`, `buy_value`, `sell_value` and `total_value`.

### Resolved within the venue

Each row's instrument is resolved from its token on its venue, as a position's is: the broker's exchange
code says an exchange and a kind - cash, derivative, currency or commodity - and the token is looked up only
among that kind's segments. Groww sends no token, so its cash orders resolve by trading symbol. INDmoney
names the company rather than a trading symbol, so its `tradingsymbol` is the resolved instrument's.

| Broker | Order book | Trade book | Fields |
| --- | --- | --- | --- |
| Zerodha | `GET /orders` | `GET /trades` | the fields of Kite's order postback |
| Dhan | `GET /v2/orders` | `GET /v2/trades` | Dhan's v2 schema |
| Flattrade, Shoonya | `POST …/OrderBook` | `POST …/TradeBook` | the fields of Noren's order update message; checked against a live Flattrade order |
| Fyers | `GET /api/v3/orders` | `GET /api/v3/tradebook` | Fyers' v3 schema and its order status codes |
| Groww | `GET /v1/order/list` | `GET /v1/order/trades/{id}` for each filled order, at once | Groww's schema |
| INDmoney | `GET /order-book` | `GET /trade-book` for `EQUITY` and `DERIVATIVE`, at once | orders checked against a live order; trades unverified |
| Kotak | `GET {base_url}/quick/user/orders` | `GET {base_url}/quick/user/trades` | the fields of Kotak's order update message |
| Stoxkart | `GET /reports/order-book` | `GET /reports/trade-book` | Stoxkart's documented schema; orders checked against rejected, after-market and cancelled orders; trades unverified |
| Wisdom Capital | `GET /interactive/orders` | `GET /interactive/orders/trades` | the fields of XTS's order event |

!!! warning "Most row field names are unverified"

    Noren's and INDmoney's order-book fields have been confirmed against live orders, Stoxkart's against
    rejected, after-market and cancelled orders only, and no trade has been read yet. Every other broker's
    order fields, and every broker's trade fields, follow its published schema or the field names of its
    order update messages, and should be checked on a day with orders and fills.

### Placing an order

`POST /api/orders/place` sends one order to one broker. The API chooses the broker, not the caller. A
broker selector ranks the brokers, and the order goes to the first one in that ranking that can take it.
The selector is named by `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR`:

| Selector | How the brokers are ranked | Redis it reads |
| --- | --- | --- |
| `round_robin` (the default) | The brokers take turns in a fixed order, and the turn is kept in a Redis counter that every gunicorn worker shares, so consecutive orders go to consecutive brokers | `INCR unified:orders:round_robin`, in the same round trip as the instrument |
| `fixed_priority` | Every order goes first to the brokers named in `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY`, in that order, and then to the rest in the usual order | none |

A new algorithm is a class of its own in `unified_broker_interface/utilities/broker_selection/`, added to the
registry there; see [`BrokerSelector`][unified_broker_interface.utilities.broker_selection.base.BrokerSelector].
Brokers excluded by `UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS` are never offered an order,
whichever selector ranks them.

!!! danger "This places real orders on live trading accounts"

    Every request without `"dry_run": true` reaches a broker, and an order the broker accepts is live at the
    exchange. It can be cancelled with [`DELETE /api/orders/cancel`](#cancelling-an-order) once its broker's order
    scripts have recorded it, or at the broker. Try a new body with `dry_run` first, which answers with the exact
    request that would have been sent and sends nothing.

The endpoint is built for latency. Before the broker's own place-order call it reads Redis only, in one to
three round trips, and it never reads MongoDB or PostgreSQL or calls a broker for anything else. It checks
no funds, takes no rate-limit slot, checks no market hours, and starts no login. Each worker keeps its HTTPS
connections to each broker open, so an order usually does not pay for a new TLS handshake; see
[Broker connections](#broker-connections).

```text
request ──► check the body (no I/O)
        ──► Redis: API token, broker logins and settings, mapping date and warm identifier (every order)
        ──► Redis: the instrument by its fields (only when there is no instrument_id, and the worker has not found it before)
        ──► Redis: the identity and every broker's order handle (only when the worker does not hold them),
                   and whatever the selector reads (nothing for fixed_priority)
        ──► rank the brokers, choose the first that can take the order, check lots and ticks (no I/O)
        ──► one POST to the broker
```

Each worker keeps the catalogue data it has read, the instrument an identity-field lookup found and the
instrument's identity and order handles, in its own memory. It trusts that copy only while Redis still
holds the same `unified:catalogue:current_date` and `unified:catalogue:warm_identifier` it was read under,
and only until midnight, when the catalogue keys expire. A new warm, a new date or midnight drops the whole
copy. Logins, settings, the API token and the round-robin counter change during the day and are read from
Redis on every order.

| Order | Round trips with `round_robin` | With `fixed_priority` |
| --- | --- | --- |
| First order for an instrument in a worker, named by its fields | 3 | 3 |
| First order for an instrument in a worker, named by `instrument_id` | 2 | 2 |
| A later order for the same instrument in the same worker | 2 | 1 |

!!! note "The warm identifier appears with the first warm after this change"

    Only a warm writes `unified:catalogue:warm_identifier`. Until one has run, the workers keep no catalogue
    data and every order reads it from Redis, as before.

#### Broker connections

A new HTTPS connection to a broker costs a TCP and TLS handshake before the order itself. Measured from this
host on 2026-09-15 with `HEAD /` and no login, a request on a new connection took 54 to 109 ms (median of three)
and the same request on an open connection 23 to 43 ms, so an open connection saves roughly 15 to 75 ms.

Brokers' servers close a connection that has been idle for a while. An order sent on a connection the server
has just closed fails with a connection error and is answered `unknown` (504), although the broker never saw
it. To rule that out, each broker's connections are never reused once they have been idle longer than a limit
set well below the server's timeout; an older connection is closed and a new one opened, which costs a
handshake and never an order. This applies whether or not warming is on.

| Broker | Server's idle timeout (measured) | Idle limit | Warming ping every |
| --- | --- | --- | --- |
| Shoonya, Wisdom Capital | 65 s (nginx) | 45 s | 15 s |
| Dhan | 240 s (AWS load balancer) | 180 s | 60 s |
| Zerodha, Fyers, Groww, INDmoney, Flattrade | 400 s (Cloudflare) | 300 s | 60 s |
| Kotak | 600 s | 300 s | 60 s |
| Stoxkart | more than 600 s (AWS load balancer) | 300 s | 60 s |

Warming is off unless `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS` names brokers. For each one, every
worker runs a background thread that sends `HEAD /` to the broker's host, with no credentials, more often than
the idle limit, so an order finds a connection that is open and recently used. Nothing a ping does can make an
order fail:

- A ping never carries or stores cookies or login headers; it bypasses the session, so the order requests are
  exactly what they were without warming.
- After a ping's answer its connection is watched for a second, and goes back to the pool only if the server
  has not closed it in that time. A connection a server closes straight after answering never reaches an order.
- Any error a ping raises is caught in its thread and logged when a broker starts and stops failing.
- A ping in progress holds its own connection; an order arriving at that moment uses another or opens one.
- A misspelt name in the variable is logged and ignored rather than stopping the API.

Kotak's host comes from its login, so its warmer starts pinging only after the worker's first Kotak request.
`python -m test_runs.connection_warming` checks all of this against a local server that misbehaves on
purpose; see [Test runs](test-runs.md).

!!! warning "The idle limits come from one measurement"

    If a broker shortens its server's idle timeout below the limit above, an order can again be answered
    `unknown` after a quiet spell. The measurement is described in the note on
    `unified_broker_interface/utilities/broker_orders/base.py` and in
    [Known issues](../contributing/known-issues.md).

The body is JSON. The vocabulary is the [shared one](../architecture/contracts.md#the-shared-vocabulary),
written in capitals, though lower case is accepted.

| Field | Required | Meaning |
| --- | --- | --- |
| `instrument_id` | this, or the fields below | The instrument's id, as `/api/instruments/details` answers it |
| `exchange`, `segment` | when there is no `instrument_id` | `nse`, `bse`, `mcx` or `ncdex`, and a segment such as `equities` or `nse_equity_options` |
| `symbol` | for a security | The trading symbol, such as `SBIN` |
| `underlying_symbol`, `expiry_date` | for a future or option | Such as `NIFTY` and `2026-09-29` |
| `strike_price`, `option_type` | for an option | Such as `25000` and `CE` |
| `transaction_type` | yes | `BUY` or `SELL` |
| `product` | yes | `CNC`, `MIS` or `NRML` |
| `order_type` | yes | `MARKET`, `LIMIT`, `SL` or `SL-M` |
| `quantity` | yes | Units, not lots, and a whole number of the broker's lots |
| `validity` | no | `DAY` (the default) or `IOC` |
| `price` | for `LIMIT` and `SL`, refused otherwise | A whole number of ticks |
| `trigger_price` | for `SL` and `SL-M`, refused otherwise | A whole number of ticks |
| `disclosed_quantity` | no | At most `quantity` |
| `after_market` | no | `true` for an after-market order |
| `tag` | no | 1 to 20 letters and digits, passed to the broker's own tag or remarks field |
| `dry_run` | no | `true` to answer with the request instead of sending it |

Orders are accepted for every segment on NSE, BSE, MCX and NCDEX except indices, which cannot be traded,
and uncategorised instruments, whose segment does not say whether they are cash instruments or derivatives;
those two are refused with `400`.

A currency or commodity order's `quantity` is in quotation units: 100 for one lot of MCX CRUDEOIL (barrels),
100 for one lot of MCX GOLD (10 grams each), 1000 for one lot of NSE USDINR. Its lot size comes only from the
morning's [contract size decision](instrument-mapping.md#contract-sizes), never from a broker's own `lot_size`,
because brokers count a lot in different units. An order on a contract whose size is not trusted today is
answered `503` with `contract_size_status` (`undecided`, `conflict`, `no_source` or `single_source`), and a
`quantity` or `disclosed_quantity` that is not a whole number of lots is answered `400`.

Accepting an order does not mean a broker takes it. Each broker lists the markets it has been confirmed for, as an
exchange, an asset class (securities, currency or commodity) and cash or derivative, and for a currency or commodity
market also how its order API counts quantity: in lots, in quotation units, or in lots times the broker's own lot
size. The route converts the quantity accordingly. A broker passes over an order in a market it does not list,
with a reason such as `does not take mcx commodity derivative orders`.

Each broker's currency and commodity markets are listed below. Every listing counts quantity as lots times
the broker's own lot size, the rule the brokers' documentation and staff give wherever they say anything;
for CRUDEOILM, one lot of 10 barrels is sent as 1 to Zerodha, Dhan, Fyers and Wisdom Capital and as 10 to Kotak,
Shoonya, Flattrade and Stoxkart.

| Broker | Markets listed | How the quantity rule is known |
| --- | --- | --- |
| Zerodha | MCX, NSE commodities (`NCO`), NSE currencies (`CDS`), BSE currencies (`BCD`) | Kite forum answers by Zerodha staff |
| Dhan | MCX | Dhan staff answers; currencies discontinued in April 2024 |
| Shoonya, Flattrade | MCX, NSE currencies | Shoonya's documented rule for derivatives; Flattrade by the shared Noren platform |
| Kotak | MCX | Inferred from Kotak's general rule; currencies not supported in its API |
| Stoxkart | MCX, NSE currencies, BSE currencies, NCDEX | Inferred; BSE currencies and NCDEX are not in its order documentation |
| Wisdom Capital | MCX, NSE commodities, NSE currencies, BSE currencies, NCDEX | XTS documentation, whose own examples contradict it |
| Fyers | MCX, NSE currencies | Unknown |
| Groww | none | A live MCX order on 2026-09-15 was refused with `GA001` "Orders are currently not supported for commodity segment."; its order documentation lists only `CASH` and `FNO` |
| INDmoney | none | Its API supports none of these markets |

!!! danger "These listings were opened on 2026-09-15 before a live order confirmed them"

    The quantity rule is confirmed by broker staff only at Zerodha and Dhan, and on 2026-09-15 neither live test
    settled it: Zerodha refused because MCX is not activated on the account, and Dhan recorded quantity 1 for one
    CRUDEOILM lot before its risk system rejected the order for insufficient funds. At every other broker a wrong rule
    would place an order many times too large or small. Try each broker with `dry_run` and check the quantity
    in the request before sending. An NCDEX `quantity` is in the unit Stoxkart's lot size counts, tonnes, not
    in the quintals prices are quoted in. See [Known issues](../contributing/known-issues.md).

For a securities order the lot is the chosen broker's `lot_size`. For every order the tick is the `tick_size` most
brokers agree on, which is what `/api/instruments/details` answers.

```bash
curl -s -X POST localhost:8080/api/orders/place -H "access-token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"exchange": "nse", "segment": "equities", "symbol": "SBIN", "transaction_type": "BUY",
          "product": "CNC", "order_type": "LIMIT", "quantity": 1, "price": "500.10", "dry_run": true}'
```

When the first broker in the ranking cannot take the order, the next one is tried, and every broker passed
over is listed in `skipped` with its reason. A broker is passed over when it is excluded by
`UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS`, has no mapping for the instrument, has no login or
no account settings in Redis, or does not take the order: INDmoney takes no `SL` or `SL-M` orders, and
Groww and Wisdom Capital take no after-market orders. Once an order has been sent it is never sent to
another broker, whatever the answer, because a second send could place the order twice.

!!! warning "Stoxkart needs its Algo-ID in a header, and no Stoxkart order has filled yet"

    SEBI's framework requires an exchange-issued Algo-ID on every API order. Stoxkart refuses an order with
    `invalid algo_id` unless the code arrives as the HTTP header `X-Algo-Id`, whatever the body's `algo_id`
    says, so this endpoint sends `X-Algo-Id: 99999` together with `"algo_id": "99999"` in the body, for NSE
    and BSE alike. The code belongs to the API app "Test App" (#30), approved under the non-registered
    strategy `NSE-BSE_NON_REGISTERED`, with the host's static IPs registered for it on Stoxkart's developer
    site.
    On 2026-09-15 orders with the header passed the Algo-ID check, and two after-market KWIL orders were
    accepted with status `AMO PENDING` and then cancelled, but no Stoxkart order has yet been placed during
    market hours or filled. See [Pitfalls](../contributing/pitfalls.md#placing-and-cancelling-orders).

```json
{
  "broker": "zerodha", "instrument_id": "ead1abb8-3a2d-5952-9552-aa77d27b8619", "tag": null,
  "outcome": "accepted", "order_id": "250915000001", "status_message": null,
  "broker_response": { "status": "success", "data": { "order_id": "250915000001" } },
  "skipped": [],
  "timing_ms": { "preparation": 0.6, "broker": 84.2 }
}
```

`timing_ms.preparation` is the API's own time before the broker call, and `timing_ms.broker` is the broker
call itself. A dry run answers `request` (the method, URL and form or JSON body, without the session
headers) and `dry_run: true` in place of the outcome.

| Status | Outcome | Meaning |
| --- | --- | --- |
| `200` | `accepted` | The broker answered with an order id, or it was a dry run |
| `422` | `rejected` | The broker refused the order, or it could not be connected to, so nothing was placed |
| `504` | `unknown` | The broker answered with a server error, did not answer in time, or answered without an order id: check the order book before sending again |
| `400` | | The body is not a valid order, or the quantity or a price is not whole lots or ticks |
| `401` | | The access token is missing, wrong or expired |
| `404` | | The instrument is not in today's mapping cache |
| `503` | | Redis cannot be read, nothing has been mapped, or no broker can take the order, with `skipped` |

A broker that refuses the session, because its token has expired, answers `rejected` with its own
message. Nothing logs in again: run `bin/<broker>/login`, and the next order uses the new token without a
restart, because the token is read from Redis on every order.

!!! warning "Orders need the mapping cache warmed for today"

    The instrument, its broker tokens and its lots and ticks come only from the `unified:catalogue:` keys in
    Redis. Those keys expire at midnight and are warmed again after the 07:45 instrument mapping, so between
    midnight and that warm every order is refused with `404`. `python -m
    stock_brokers.instruments.mapping.utilities.warm_cache` warms them by hand. See
    [Known issues](../contributing/known-issues.md).

### Cancelling an order

`DELETE /api/orders/cancel` cancels one order, named by the broker's own `order_id`, at the broker whose order
book holds it. The caller does not say which broker: the API looks the id up in every broker's
`<broker>:orders:orders` hash in Redis, which each broker's order book poller and order update websocket keep,
and sends the cancel to the one broker whose hash holds it.

!!! danger "This cancels real orders on live trading accounts"

    Every request without `"dry_run": true` reaches a broker. Try it with `dry_run` first, which answers with
    the exact request that would have been sent and sends nothing.

The endpoint is built the way placement is. Before the broker's cancel call it reads Redis once, in one
round trip, and it never reads MongoDB or PostgreSQL. It reuses the same open HTTPS connection per broker as
placement.

```text
request ──► check the parameters (no I/O)
        ──► Redis: API token, broker logins and settings, and the order id in all ten orders hashes
        ──► find the one broker holding the order, refuse a finished order (no I/O)
        ──► one request to that broker
```

The parameters can be sent as a JSON body or in the query string.

| Field | Required | Meaning |
| --- | --- | --- |
| `order_id` | yes | The broker's order id, as `POST /api/orders/place` and `GET /api/orders/details` answer it |
| `broker` | no | The broker's name, needed only when two brokers hold an order with the same id |
| `dry_run` | no | `true` to answer with the request instead of sending it |

```bash
curl -s -X DELETE localhost:8080/api/orders/cancel -H "access-token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"order_id": "26091500012345", "dry_run": true}'
curl -s -X DELETE "localhost:8080/api/orders/cancel?order_id=26091500012345&broker=shoonya" -H "access-token: $TOKEN"
```

An order becomes cancellable only once its broker's scripts have recorded it. The poller reads the order book
every half second, every five seconds at Fyers and every second at Stoxkart, and the websocket records an
order as the broker pushes it, so an order placed a moment ago can still be answered `404`. A Stoxkart order
is found once its poller or its order socket has recorded it. Stoxkart's socket sent nothing when two
after-market orders were placed on 2026-09-15, so such an order is found only after the next order book
poll, within about a second. Flattrade and Shoonya both number orders as the date followed by eight digits,
so the same id can turn up at both. Such an id is answered `409` with the brokers listed, and the request is
sent again with `broker`.

Each broker's cancel request is shown below. Five brokers need a value besides the order id, which is read
from the broker's own copy of the order kept beside the normalized one in Redis, or at Stoxkart first from
a `variety` stored beside that copy.

| Broker | Request | Value read from the stored order |
| --- | --- | --- |
| Zerodha | `DELETE /orders/{variety}/{order_id}` | `variety`, `regular` when absent |
| Dhan | `DELETE /v2/orders/{order_id}` | none |
| Fyers | `DELETE /api/v3/orders/sync` with `{"id"}` | none |
| Groww | `POST /v1/order/cancel` with `{"groww_order_id", "segment"}` | `segment`; answered `503` when absent |
| INDmoney | `POST /order/cancel` with `{"order_id", "segment"}` | `segment`; when absent, `DERIVATIVE` for an id starting `DRV` and `EQUITY` otherwise |
| Kotak | `POST {base_url}/quick/order/cancel` with `jData={"on", "am": "NO"}` | none |
| Flattrade, Shoonya | `POST …/CancelOrder` with `jData={"uid", "norenordno"}` | none |
| Stoxkart | `DELETE /orders/{variety}/{order_id}` with the header `X-Algo-Id: 99999` | the entry's top-level `variety`, then `data.variety`, then `normal`, in lower case, because Stoxkart spells it `NORMAL`, `AMO` or `BO` |
| Wisdom Capital | `DELETE /interactive/orders` with `appOrderID`, `orderUniqueIdentifier` and `clientID` | `OrderUniqueIdentifier`, `ubi` when absent |

Groww's order update websocket does not send an order's segment, so an order the websocket recorded last is
answered `503` until the next order book poll replaces its entry, within about half a second.

Stoxkart's variety is read first from a `variety` field that its two order scripts keep beside `data` in
each `stoxkart:orders:orders` entry, rather than from `data` alone, because Stoxkart's order socket
reported `NORMAL` for after-market orders whose order book row said `AMO`. The poller stores the order
book row's variety, and `bin/stoxkart/order_updates` keeps an `AMO` or `BO` variety already stored.
Stoxkart's cancel is the only one confirmed live: on 2026-09-15 it cancelled two after-market KWIL orders,
one on NSE and one on BSE, each answered HTTP 200 with outcome `accepted` and
`Order Submitted For Cancellation` in about 178 ms of broker time, and the order book then showed
`AMO CANCELLED`.

```json
{
  "broker": "shoonya", "order_id": "26091500012345", "status_before_cancel": "OPEN",
  "outcome": "accepted", "status_message": null,
  "broker_response": { "stat": "Ok", "result": "26091500012345" },
  "timing_ms": { "preparation": 0.4, "broker": 61.8 }
}
```

`status_before_cancel` is the order's status in Redis when the cancel was sent. An `accepted` cancel means
the broker took the request, not that the exchange has cancelled the order, which can still fill in the
meantime: the order book shows the result within a poll. A dry run answers `request` and `dry_run: true` in
place of the outcome.

| Status | Outcome | Meaning |
| --- | --- | --- |
| `200` | `accepted` | The broker accepted the cancel, or it was a dry run |
| `422` | `rejected` | The broker refused the cancel, or it could not be connected to, so nothing was sent |
| `504` | `unknown` | The broker answered with a server error or did not answer in time: check the order book |
| `400` | | `order_id`, `broker` or `dry_run` is missing or malformed |
| `401` | | The access token is missing, wrong or expired |
| `404` | | No broker's order book in Redis holds the order id |
| `409` | | The order is already `COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED`, or two brokers hold the id |
| `503` | | Redis cannot be read, or it holds no login or settings for the broker, or no segment for a Groww order |
