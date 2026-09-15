# Notes on `unified_broker_interface/blueprints/orders.py`

## Why `place` is one long method

The earlier order placement endpoint took about half a second to answer, and most of that time was the API's own work rather than the broker's. It was spread across a write service, a router, rate limits, a funds reader and one builder module per broker, and each layer added reads of its own. The user asked for all of the placement logic to live inside the one `place` method, so that everything an order costs can be read top to bottom in one place and nothing can quietly add a round trip. The per-broker branches are therefore written out in full inside the method rather than shared, which is deliberate duplication.

## What an order costs

A request makes at most three Redis round trips and one broker call.

| Step | I/O |
| --- | --- |
| Token check | Pipeline A: the API token, the mapping date, `HMGET last_login` and `HMGET settings` for all ten brokers |
| Instrument by its fields | One `ZRANGEBYLEX` on the segment's catalogue, only when there is no `instrument_id` |
| Instrument and turn | Pipeline B: the identity, the order handles and `INCR unified:orders:round_robin` |
| Send | One POST to the chosen broker |

Measured on 2026-09-15 against a local Redis, a dry run took about 0.3 ms of the method's own time in the Flask test client and about 1.5 ms end to end over HTTP through gunicorn. In the same test, patched MongoDB and PostgreSQL entry points were never called.

## What was deliberately left out, and why

Every item below cost at least one round trip in an earlier version.

- **Funds checks.** The removed router asked every eligible broker for its balance, one after another, before choosing one.
- **Quotes.** A market order's value was priced from a live quote so that funds could be checked.
- **Rate-limit slots.** `INCR` and `DECR` on per-window keys, and in the oldest version a `time.sleep`.
- **The daily placed-order counter.** It was used only to spread load, which the round robin now does.
- **Market-hours checks.** They read `exchange_details` with a MongoDB fallback. The broker refuses an order outside market hours anyway.
- **Broker client construction.** `BrokerAPI.__init__` reads MongoDB twice, and each broker's constructor probes a profile endpoint and may log in with Selenium. The method reads the token and account fields from the Redis `last_login` and `settings` hashes instead.
- **Relogin.** On a refused session the old service started `<broker>-login.service` through `systemctl`. The new method answers `rejected` with the broker's message.
- **MongoDB and PostgreSQL fallbacks.** `@authenticated` falls back to MongoDB when Redis has no token, so the token check is written out inline without that fallback. The mapping cache falls back to PostgreSQL on a miss, so the method reads the Redis keys directly and answers `404` or `503` instead.

## Connection reuse

`requests.request` opens a new TCP and TLS connection for every call, which alone can cost a hundred milliseconds or more. The blueprint keeps one `requests.Session` per broker, created under a lock on the first order to that broker, so later orders from the same worker reuse the open connection. urllib3's pool is safe to share between the worker's threads, and none of the order calls rely on cookies.

## The round robin

The turn is `INCR unified:orders:round_robin` modulo the number of brokers not excluded. A Redis counter was chosen over an in-process one because gunicorn runs two workers, and a counter in each would let the same broker take two orders in a row. The counter is incremented only after the body has passed its checks, so a malformed request does not use up a turn. It is incremented before the broker is chosen, though, so an order refused for its lot size or tick size still uses up a turn.

When the broker whose turn it is cannot take the order, the method walks forward to the next broker, which means the broker after a skipped one takes two turns in a row. Nothing is retried once a request has been sent, because a timeout or a server error does not prove the order was not placed.

## Where each broker's request comes from

The request bodies, exchange codes and response readers were copied from the `build_place`, `account_fields`, `written_order_id`, `write_error` and `is_rejection` methods under `unified_broker_interface/utilities/broker_orders/` as they stood before commit 4cc8c91. They can be read with `git show 4cc8c91^:unified_broker_interface/utilities/broker_orders/<broker>.py`, and Noren's with `.../utilities/noren.py`. The session headers were copied from each `_request` in `stock_brokers/api/<broker>.py`.

A few details matter:

- Flattrade's and Shoonya's body is `jData=<json>&jKey=<token>`, with `&` in the JSON escaped as `&`, because Noren splits the body on the ampersand before parsing the JSON, so a symbol such as `M&M` would otherwise end the field early.
- Kotak's host comes from `base_url` in its stored login, normalized the way `KotakAPI.base_url` does it.
- Wisdom Capital is sent with certificate verification off, as its API class does, because its certificate does not match its host.
- Groww's `order_reference_id` must be 8 to 20 characters with at most two hyphens, which is why it is the tag's first seven characters, a hyphen and twelve hex digits.

## How outcomes are decided

An HTTP status below 500 at or above 300 is `rejected`, because the broker validated and refused the request. A 5xx is `unknown`, unless the broker's error code is one the removed code treated as a settled refusal, such as Kite's `OrderException` or Groww's `GA004`. A 2xx with a refusal in its body, such as Noren's `stat` of `Not_Ok`, is `rejected`. A 2xx with no order id is `unknown`. A connect timeout is `rejected`, because the request never left, and any other network error is `unknown`.

## Segments that are refused

Only NSE and BSE cash instruments and equity and fixed income derivatives are sent. Every removed builder had exchange codes for exactly those, and refused commodity and currency derivatives because brokers may count their quantity in lots, which has not been confirmed. Indices are refused because they cannot be traded, and uncategorised instruments are refused because their segment says nothing about which exchange code to send.

## The midnight gap

The `unified:catalogue:` keys expire at midnight and are warmed after the 07:45 mapping, so the endpoint refuses every order in between. Falling back to PostgreSQL would break the rule that an order never waits on the database. This is recorded in `docs/contributing/known-issues.md`.

## How `cancel` finds the broker

A cancel names only the broker's order id, so the method has to work out which broker holds it. Three ways were weighed with the user on 2026-09-15: look the id up in the `<broker>:orders:orders` hashes that the order scripts already keep, record each order's broker when `place` sends it, or both. The user chose the hashes. They need no change to `place`, and they also hold orders placed outside the API, such as from a broker's own app. The cost is that an order is found only after a poll or a websocket update has recorded it. Stoxkart streams no order updates, so a Stoxkart order is found only once `bin/stoxkart/orders`, which polls once a second, has recorded it.

The lookup is one pipeline: the API token, `HMGET last_login` and `HMGET settings` for all ten brokers, and one `HGET <broker>:orders:orders <order_id>` per broker. The id is looked up at every broker rather than guessed from its shape, because Flattrade's and Shoonya's ids have the same shape, the date followed by eight digits. When two brokers hold the id the method answers `409` and asks for `broker`, rather than cancelling at either.

Because the order id is sent before the token is checked, a malformed `order_id` is answered `400` before a wrong token is answered `401`. A missing `access-token` header is still answered `401` first, before any parameter is read.

## Values a cancel needs besides the order id

Four brokers need a second value, and the method reads it from the broker's own copy of the order under `data` in the hash entry, instead of fetching the order book as the removed code did, which would have cost a second broker call.

| Broker | Value | When the stored order lacks it |
| --- | --- | --- |
| Zerodha | `variety`, such as `regular` or `amo` | `regular`. Kite's postback carries `variety`, so the websocket entry has it too. |
| Stoxkart | `variety`, lowercased, because Stoxkart's order book spells it `NORMAL`, `AMO` or `BO` while its cancel path is `/orders/normal/{order_id}` | `normal`, as the removed code did. `bin/stoxkart/orders` has recorded Stoxkart orders since 2026-09-15, but no Stoxkart order has been cancelled through the API. |
| Groww | `segment`, `CASH` or `FNO` | Answered `503`. Groww's websocket update, `orderDetailUpdateDto`, carries no segment, and a wrong segment would only be refused, so the method waits for the next poll to replace the entry rather than guess. |
| INDmoney | `segment`, `EQUITY` or `DERIVATIVE` | Guessed from the id. Live equity ids look like `EQ-100072817`; the `DRV` prefix for derivatives comes from the older cancel code and has not been seen live. |
| Wisdom Capital | `OrderUniqueIdentifier` | `ubi`, the value `place` sends when there is no tag. |

Kotak's `am` is always `NO`, copied from the removed `build_cancel`. Kotak's order book field for an after-market order has not been identified, so reading it was not attempted.

A finished order, one whose stored status is `COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED`, is refused without calling the broker, because those statuses never change back. An `OPEN` status may be half a second stale, so an order that has just filled is still sent, and the broker refuses it.

## How cancel outcomes are decided

The rules are those of `place`, simplified. An HTTP status from 300 to 499 is `rejected`, and a 5xx is `unknown`. The per-broker lists of error codes that `place` treats as settled refusals on a 5xx were left out, because an unknown cancel costs the caller only a look at the order book, whereas an unknown placement risks a duplicate order. A 2xx whose body carries a refusal, in the same fields `place` reads, is `rejected`, and any other 2xx is `accepted`, since a cancel's response has no order id to wait for. `accepted` means the broker took the request, not that the exchange has cancelled the order.

## How `cancel` was checked

On 2026-09-15 the method was run in-process with the Flask test client against Redis database 15, filled with made-up logins, settings and orders and emptied afterwards, with `requests.Session.request` stubbed. The checks covered a dry run for each of the ten brokers, every refusal before the broker call, the two-broker `409`, the Groww `503`, and accepted, rejected and unknown answers from stubbed responses and timeouts. No cancel has been sent to a live broker.

## Why Kotak refuses orders

On 2026-09-15 a live Kotak order was answered `{"stCode": 100008, "errMsg": "unauthorized", "stat": "Not_Ok"}` while Kotak's order book, positions and funds reads with the same stored token kept working. Kotak's static IP page, https://www.kotakneo.com/platform/kotak-neo-trade-api/static-ip-details/, documents `100008` as the answer to a place, modify or cancel request from an IP address that is not whitelisted, and `1037` as the answer when the session was created from a different IP. The token's JWT `scope` is `Trade`, so the stored session is not a view-only one. The host reaches Kotak over IPv4 only, from 122.166.249.222 on that day, and that address has to be registered in the Kotak Neo app under More → Trade API.

Kotak's official SDK, `Kotak-Neo/Kotak-neo-api-v2` (archived on 2026-09-10), builds the place request in `neo_api_client/api/order_api.py` slightly differently from this method, and these differences were not tested:

| Detail | Kotak's SDK | This method |
| --- | --- | --- |
| Query string | `sId=<hsServerId>` from the Login Validate response | none; the login does not store `hsServerId` |
| `neo-fin-key` header | not sent on order calls | sent |
| Order source | `os: NEOTRADEAPI` in `jData` | not sent |
| Tag field | `ig` | `rm` |

Registering the IP was enough. Later that day, with 122.166.249.222 whitelisted, the same request, still without `sId` or `os` and on the session logged in at 00:00, was accepted as order 260915000204304 and filled at 41.28, in 90.4 ms at the broker. The differences above are therefore not needed today, but they are the first things to try if Kotak starts refusing this request shape. The order book showed the order's `tag` as empty although `rm` was sent, so Kotak may keep the tag only in `ig`, which has not been checked.
