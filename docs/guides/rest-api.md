# REST API

The `unified_broker_interface` package is a Flask application that puts one HTTP interface in
front of the project. A client logs in with an api key and secret, receives an access token, and
sends that token with every other request.

Six groups of endpoints are served today: the session, the user, broker and exchange details, the
[instruments](#instruments), the [portfolio](#portfolio) - funds, holdings and positions - and
[orders](#orders) - today's order book and trade book, and placing, modifying and cancelling.

## Running it

```bash
rest-api                 # gunicorn, two workers of four threads, on 127.0.0.1:8080
rest-api --workers 4 --threads 8
rest-api --dev           # Flask's development server, for local debugging
```

The workers are threaded, so a long stream or a slow broker quote holds one thread rather than a whole
worker, and is not cut off by gunicorn's timeout for a hung worker. The address and the token lifetime
come from the environment. All three variables are optional.

| Variable | Default | Meaning |
| --- | --- | --- |
| `UNIFIED_BROKER_INTERFACE_API_HOST` | `127.0.0.1` | Address to bind |
| `UNIFIED_BROKER_INTERFACE_API_PORT` | `8080` | Port to bind |
| `UNIFIED_BROKER_INTERFACE_API_TOKEN_TTL_SECONDS` | `86400` | How long an access token is accepted |

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
| `POST` | `/api/orders/place` | `access-token` header | Places an order at the broker the API chooses |
| `PUT` | `/api/orders/modify` | `access-token` header | Modifies a pending or open order |
| `DELETE` | `/api/orders/cancel` | `access-token` header | Cancels a pending or open order |

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
| `/details` | an instrument, `date` | Identity, `mapping_date`, seen dates, `carried_by` each broker's token, order symbol, lot and tick size | Redis |
| `/ltp` | an instrument | Identity, `last_price`, `last_trade_time`, `received_at`, `source` | Quote cache or broker |
| `/ohlc` | an instrument | The above with `ohlc`, `previous_close`, `change_percent` | Quote cache or broker |
| `/quote` | an instrument | The whole [unified quote](../architecture/contracts.md#the-unified-quote), depth included, with `source` | Quote cache or broker |
| `/prices` | an instrument, `interval`, `from` and `to` or `days`, `adjusted` (true), `known_as_of` | `{identity, interval, adjustable, price_basis, columns, candles}` | `unified.price_history` |
| `/ticks` | an instrument, `start`, `end`, `adjusted` (true) | **Streamed** JSON array of stored ticks, `start <= time < end`, oldest first; `X-Price-Basis` header | `unified.ticks` |

**An instrument** is either `instrument_id`, or `exchange`, `segment` and the identity fields its shape
needs: `symbol` for a security; `underlying_symbol` and `expiry_date` for a future; those and
`strike_price` and `option_type` for an option. Names are matched case-insensitively. `segment` may be
the stored value (`nse_equities`) or the bare name (`equities`).

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
buckets. The brokers are the nine with scripts in `bin/<broker>/` - Stoxkart has none, so it is not included.

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

Each broker's module in `unified_broker_interface/utilities/broker_funds/` reads its own response into these
buckets. Where a broker states what can back a new order, that figure is the available balance; where it
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
| Wisdom Capital | `GET /interactive/user/balance` | `netMarginAvailable` | none |

!!! warning "Stoxkart and Fyers"

    Stoxkart has no `bin/stoxkart/` scripts beyond its instrument download, so it is not in the document.
    Fyers allows an app 200 requests a minute and 100,000 a day, so `bin/fyers/` polls funds every thirty
    seconds, trades every fifteen and orders and positions every five, and its history download is held to
    half a request a second. When Fyers rate limits a poller it pauses five minutes, thirty after a
    Cloudflare ban, and Fyers shows `stale` meanwhile.

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
| Wisdom Capital | `GET /interactive/portfolio/positions`, `NetWise` and `DayWise` | `ExchangeInstrumentId`, `ExchangeSegment` | `Quantity`; `net` and `day` |

!!! warning "No position has been read back yet"

    Every account was flat when this was written. Only the empty
    answers were seen live: `[]` from Dhan and INDmoney, `{"net": [], "day": []}` from Zerodha, `{"positions":
    []}` from Groww, `{"positionList": []}` from Wisdom Capital on both bases, Noren's `Not_Ok` "no data",
    and Kotak's `stCode` 5203. The field names inside a row follow each broker's published schema, and
    INDmoney's, which has none, an unconfirmed reading. Check them on a day with an
    open position.

## Orders

Everything under `/api/orders` takes the `access-token` header and answers `GET`.

| Path | Parameters | Returns | Answered from |
| --- | --- | --- | --- |
| `/details` | none | Today's orders at every broker, and how each broker's data was read | `unified:orders:orders`, written by `bin/unified/orders` every half second |
| `/trades` | none | Today's trades at every broker, and how each broker's data was read | `unified:orders:trades`, written by `bin/unified/trades` every half second |

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
| Wisdom Capital | `GET /interactive/orders` | `GET /interactive/orders/trades` | the fields of XTS's order event |

!!! warning "Most row field names are unverified"

    Noren's and INDmoney's order-book fields have been confirmed against live orders, and no trade has been
    read yet. Every other broker's
    order fields, and every broker's trade fields, follow its published schema or the field names of its
    order update messages, and should be checked on a day with orders and fills.

### Placing, modifying and cancelling

!!! danger "These move real money"

    Every write reaches a live broker account unless `dry_run` is true. Seven brokers write, and no order has
    yet been sent to any of them through this API: every broker's calls have been built and checked offline
    with the broker faked, placements dry-run over HTTP, and a cancel sent to each writing broker for an
    order id its live order book does not hold.

| Route | Body | Answers |
| --- | --- | --- |
| `POST /place` | an instrument - `instrument_id`, or `exchange`, `segment` and identity fields as `/api/instruments` takes them - with `transaction_type`, `product`, `order_type`, `validity` (`DAY`), `quantity` in units, `price`, `trigger_price`, `disclosed_quantity`, `after_market`, `tag`, `dry_run` | `broker`, `instrument_id`, `outcome`, `order_id`, `status_message`, `tag`, `routing` |
| `PUT /modify` | `broker`, `order_id`, any of `quantity`, `price`, `trigger_price`, `order_type`, `validity`, `disclosed_quantity`, and `dry_run` | `broker`, `order_id`, `outcome`, `status_message` |
| `DELETE /cancel` | `broker`, `order_id`, `dry_run` | the same |

The fields are the order contract's vocabulary - `BUY`/`SELL`, `CNC`/`MIS`/`NRML`, `MARKET`/`LIMIT`/`SL`/`SL-M`,
`DAY`/`IOC` - read case-insensitively, and a body may be JSON or query parameters.

```bash
curl -s -X POST localhost:8080/api/orders/place -H "access-token: $TOKEN" -H "Content-Type: application/json" \
     -d '{"exchange": "nse", "segment": "equities", "symbol": "SBIN", "transaction_type": "BUY", "product": "CNC",
          "order_type": "LIMIT", "quantity": 1, "price": "800.00", "tag": "example1", "dry_run": true}'
curl -s -X DELETE localhost:8080/api/orders/cancel -H "access-token: $TOKEN" -H "Content-Type: application/json" \
     -d '{"broker": "zerodha", "order_id": "250914000010"}'
```

**The API chooses the broker.** A placement names no broker. Every broker that carries the instrument, writes
through this API, takes the order type and has room in its order limits is a candidate; a delivery buy also
needs a live available balance of at least the order's value - price times quantity, or for a market order the
unified quote's last price plus 1%. The candidates are ranked by how many orders the API has placed at each
today, then by a fixed preference. `routing` lists every broker with whether it was eligible and why not.
Intraday, carry-forward and derivative orders are not funds-checked: the margin they need is left to the
broker's own risk checks.

**Checked before sending.** `LIMIT` and `SL` need a price and `SL` and `SL-M` a trigger price, and a type
refuses one it does not take; the quantity must be whole lots and the prices whole ticks at the chosen broker;
`disclosed_quantity` cannot exceed the quantity; `tag` is 1 to 20 letters and digits. A modification or
cancellation reads the order from the broker's order book first: `404` when the book does not hold it, `409`
when it is no longer pending or open.

**`dry_run`** builds the broker call - method, URL and body - and returns it with the routing, sending
nothing. The session headers the broker's API client adds are not shown.

**Three outcomes, never retried.**

| `outcome` | Status | Meaning |
| --- | --- | --- |
| `accepted` | `200` | The broker took it; `order_id` is the broker's |
| `rejected` | `422` | The broker refused it, or it could not be sent; nothing happened |
| `unknown` | `504` | A timeout, dropped connection or broker failure - it may have reached the exchange |

After `unknown`, find the order in `/api/orders/details` - by `tag` for a placement - before sending anything
again. A write refused for a dead session is the one exception: the refusal is certain, so when another process
has already stored a newer session the write is sent once more with it. Otherwise the broker's login unit is
started and the write is `rejected`, nothing sent - send it again once the login has run. Every write takes a slot in the broker's order limits first and is
refused with `429` and a retry time when there is none. `503` means no broker could take the placement, and
`501` a broker that does not write through the API yet.

**Cash and equity derivatives only, for now.** Commodity and currency derivatives are refused at every broker:
several count their order quantity in lots where every other order is in units, and that has not been confirmed
for any of them.

| Broker | Place | Modify | Cancel | Limits |
| --- | --- | --- | --- | --- |
| Zerodha | `POST /orders/regular`, or `/orders/amo` | `PUT /orders/{variety}/{order_id}`, changed fields only | `DELETE /orders/{variety}/{order_id}` | |
| Dhan | `POST /v2/orders` | `PUT /v2/orders/{orderId}`, whole order restated | `DELETE /v2/orders/{orderId}` | |
| Flattrade, Shoonya | `POST …/PlaceOrder` | `POST …/ModifyOrder`, whole order restated | `POST …/CancelOrder` | a refused session inside a 200 is logged in again |
| Groww | `POST /v1/order/create` | `POST /v1/order/modify`, type, quantity and prices only | `POST /v1/order/cancel` | no after-market orders; `tag` answered as Groww's unique `order_reference_id` |
| INDmoney | `POST /order` | `POST /order/modify`, quantity and limit price only | `POST /order/cancel` | market and limit orders only |
| Wisdom Capital | `POST /interactive/orders` | `PUT /interactive/orders`, whole order restated | `DELETE /interactive/orders` | no after-market orders |
| Kotak | built | built | built | **not enabled** - the API app is read-only |
| Fyers | built | built | built | **not enabled** - the app is not approved for placing orders |
| Stoxkart | built | built | built | **not enabled** - no live session and no algo identifier |

A broker that is not enabled is never routed to, and a modify or cancel naming it answers `501` with the
reason. The broker's own refusal codes decide between `rejected` and `unknown`: Kite's `InputException` and
`OrderException`, Dhan's input and order errors, Noren's `Not_Ok`, Groww's `GA001`, `GA004` to `GA007`, INDstocks'
validation and order errors and XTS's `e-orders` and `e-rms` codes settle a write; anything else leaves it
unknown. A price is checked against the instrument's tick in rupees from Zerodha, Fyers, Groww, Shoonya or
Wisdom Capital, because Dhan, Kotak, INDmoney and Stoxkart map the tick in paise.
