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
