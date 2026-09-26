# Notes on `unified_broker_interface/blueprints/orders.py`

## How the order routes are split, and the rule that keeps them fast

The earlier order placement endpoint took about half a second to answer, and most of that time was the API's own work rather than the broker's. It was spread across a write service, a router, rate limits, a funds reader and one builder module per broker, and each layer added reads of its own. The user first asked for all of the placement logic to live inside the one `place` method, so that everything an order costs could be read top to bottom in one place and nothing could quietly add a round trip.

On 2026-09-15 the user asked for the method to be split up again, after measuring that a Python method call costs about 16 nanoseconds against about 122 microseconds for one Redis round trip, so the split costs nothing measurable. The protection the one-method rule gave is kept by a different rule instead: every Redis read the order routes make is in this module, and the only network call is `BrokerOrders.send` in `unified_broker_interface/utilities/broker_orders/base.py`. The broker classes are handed decoded dictionaries and read no store, so the round trips an order costs can still be counted by reading this file.

| Piece | Holds |
| --- | --- |
| `OrdersBlueprint` in this module | The token check, every Redis pipeline, the catalogue lookup and the modify and cancel answers |
| `OrderPlacement` | Everything a placement does once Redis has been read: the turn, ranking, choosing the broker, building the request, sending it and the place answer |
| `PreparedPlacement` | One order with a broker and a built request, not yet sent |
| `RefusedRequestError` | A request answered without calling a broker, as a body and a status both processes can read |
| `PlaceOrderRequest`, `ModifyOrderRequest`, `CancelOrderRequest` | Validation of the body and query string, which costs no I/O; the checks all three share live in `OrderRequest` |
| `OrderModification` | A stored order with a modification's changes laid over it, which also costs no I/O |
| `Instrument` and `TradeableSegments` | The instrument's segment, whether orders are sent for it, its market key, and decoding all of that from the text Redis holds |
| One `BrokerOrders` subclass per broker | The skip checks, the request, the reading of success answers and which server errors are settled refusals |
| `BrokerOrders` itself | The HTTP call, error answers, the accepted, rejected and unknown rules, and decoding its own login and settings |

On 2026-09-23 the placement half was moved again, into `OrderPlacement` in `unified_broker_interface/utilities/broker_orders/utilities/placement.py`, so that the order engine can place an order without building a blueprint. The rule above is unchanged and is what the new class was written around: it reads no store, and the blueprint still makes every Redis call and still calls `rotation()` itself so that the "every broker is excluded" refusal keeps costing one round trip rather than two. `orders.py` fell from 1352 lines to 1030, and all 618 recorded scenarios matched unchanged.

The split was checked with `python -m test_runs.order_routes`, whose recording was made before it: all 440 scenarios, including every outgoing request's headers, body, timeout and certificate check, matched unchanged.

A refusal that is answered without calling a broker is raised as `RefusedRequestError` and turned into its JSON answer in `place`, `modify` and `cancel`, so each step can be a method of its own without every caller checking a returned status.

## The placement mode, and why it is a switch rather than a branch in git

The order engine replaces this module's broker call with a handoff to a daemon, so that an order can outlive the HTTP request that asked for it and become a bracket, an OCO pair or a chaser. That is a large change to the one path in this project that spends real money, and merging it would leave no way back except reverting a commit under pressure during a session.

`UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` is the way back. At `direct` the module behaves exactly as it always has, so the engine's code can be merged into `main` long before anyone trusts it, and a session that goes wrong is recovered with an environment variable and a restart. `ORDER_PLACEMENT_MODES` lists the two accepted values, and `__init__` refuses anything else with a `ValueError`, exactly as it already refuses an unknown broker selector. Both checks are deliberately fatal: a misspelt mode that quietly fell back to `direct` would look like a working engine that silently was not one, which is the worst of the three outcomes.

The mode is read once in `__init__` rather than per request, because it cannot change without a restart and because reading it per request would put a dictionary lookup on the measured path for no benefit.

## What an order costs

A request makes at most three Redis round trips and one broker call.

| Step | I/O |
| --- | --- |
| Token check | Pipeline A: the API token, the mapping date, `HMGET last_login` and `HMGET settings` for all ten brokers, and the warm identifier |
| Instrument by its fields | One `ZRANGEBYLEX` on the segment's catalogue, only when there is no `instrument_id` and the worker's `InstrumentCache` has not kept the lookup |
| Instrument and selector | Pipeline B: the identity and the order handles unless the cache holds them, and the selector's commands, such as `INCR unified:orders:round_robin`; the pipeline is not sent when it holds no command |
| Send | One POST to the chosen broker |

Measured on 2026-09-15 against a local Redis, before the split and the cache, a dry run took about 0.3 ms of the method's own time in the Flask test client and about 1.5 ms end to end over HTTP through gunicorn. In the same test, patched MongoDB and PostgreSQL entry points were never called.

## What a worker keeps in memory, and why only that

On 2026-09-15 the user asked for everything the route reads from Redis that does not change during the day to be kept in process memory, falling back to Redis only when the kept copy is not valid. Each read was classified:

| Read | Changes during the day | Kept |
| --- | --- | --- |
| The API token | Yes, on every connect | No |
| Broker logins | Yes, on every login; a new Zerodha login invalidates the previous token | No |
| Broker settings | Rarely, but `BrokerAPI.__init__` rewrites them from MongoDB on every construction and nothing marks a real change; they ride in pipeline A, which runs anyway, so keeping them would save no round trip | No |
| Mapping date and warm identifier | Once per warm | No, they are what the copy is checked against |
| The catalogue lookup, identity and order handles | Only when a warm runs | Yes |
| The round-robin counter | On every order | No |

The mapping date alone could not validate the copy, for two reasons found while designing it. A warm re-run for the same date rewrites the dated hashes without changing `current_date`, which is why `MappingRedisTier.write_current_date` now also writes a new `warm_identifier` in the same transaction. And the dated keys expire at midnight while `current_date` does not, so without its own midnight check a worker would keep answering from yesterday's mapping through the night while Redis answers `404`. The copy is therefore trusted only under the same date and identifier and only until the midnight after it was first filled, and when Redis holds no identifier nothing is kept at all.

The copy fills one instrument at a time, as orders ask for them, rather than loading the catalogue. On 2026-09-15 the catalogue held 527,779 instruments, whose identity and order handle hashes took 215 MB and 277 MB in Redis, which is too much to hold twice per worker. Each store is emptied when it reaches 10,000 entries. Misses are never kept, because the mapping cache's own fall-through can add an instrument to Redis later in the day. The identity and handles are kept as the text Redis returned and decoded on every order, so no order can change what a later order reads.

A consequence recorded by the `repeat_order_after_handles_change_within_one_warm` scenario of `test_runs/order_routes.py` is that an order handle rewritten in Redis without a new warm is not seen by a worker that already holds the instrument. Nothing in the project rewrites handles in place today.

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

`requests.request` opens a new TCP and TLS connection for every call. Each broker's `BrokerOrders` instance keeps one `requests.Session`, and the blueprint builds one instance per broker when it is built, so once per gunicorn worker, and later orders from the same worker reuse the open connection. The session used to be created lazily under a lock on the first order to a broker; creating it in the constructor opens no connection, so the lock is gone.

On 2026-09-15 the user asked for connections to be kept warm, with the hard condition that warming must never make an order fail in any case, such as a closed connection. The idle limit, the warming pings and the measurement behind their numbers are described in the note on `unified_broker_interface/utilities/broker_orders/base.py`. `start_connection_warmers` catches everything and ignores unknown names, because a warming setting that stopped the API would itself make orders fail.

## Choosing the broker

On 2026-09-15 the user asked for the round robin to be replaceable by other selection methods, which can be plugged in and out. The choice is split in two. A `BrokerSelector` from `unified_broker_interface/utilities/broker_selection/` only ranks the brokers, and the blueprint walks that ranking and asks each broker's `BrokerOrders.place_skip_reason` whether it can take the order. The skip reasons therefore stay with the brokers they describe, whichever selector is configured, and `skipped` lists the brokers passed over before the chosen one exactly as it did before selectors existed. The blueprint also ignores any ranked name that is not in the rotation, so no selector can send an order to an excluded broker.

A selector reads no store itself. `queue_redis_commands` adds its commands to the pipeline that also reads the instrument, so a selector never adds a round trip of its own. The selector is chosen by name from configuration when a worker starts, and an unknown name raises `ValueError` so the worker does not start, rather than routing orders some other way. The registry is a plain dictionary of classes, not an import by name, following the user's rule against dynamic power features.

`record_outcome` runs after the broker has answered. The blueprint catches and logs any exception from it, because by then the order has been sent and a selector's bug must not turn a placed order into an HTTP 500.

### The round robin

`RoundRobinSelector` keeps the original algorithm. The turn is `INCR unified:orders:round_robin` modulo the number of brokers not excluded. A Redis counter was chosen over an in-process one because gunicorn runs two workers, and a counter in each would let the same broker take two orders in a row. The counter is incremented only after the body has passed its checks, so a malformed request does not use up a turn. It is incremented before the broker is chosen, though, so an order refused for its lot size or tick size still uses up a turn.

When the broker whose turn it is cannot take the order, the method walks forward to the next broker, which means the broker after a skipped one takes two turns in a row. Nothing is retried once a request has been sent, because a timeout or a server error does not prove the order was not placed.

### Fixed priority

`FixedPrioritySelector` is the second algorithm, written so that there is more than one to plug in. It reads the preference once, when the worker starts, and queues no Redis command.

## Where each broker's request comes from

The request bodies, exchange codes and response readers were copied from the `build_place`, `account_fields`, `written_order_id`, `write_error` and `is_rejection` methods under `unified_broker_interface/utilities/broker_orders/` as they stood before commit 4cc8c91. They can be read with `git show 4cc8c91^:unified_broker_interface/utilities/broker_orders/<broker>.py`, and Noren's with `.../utilities/noren.py`. The session headers were copied from each `_request` in `stock_brokers/api/<broker>.py`.

A few details matter:

- Flattrade's and Shoonya's body is `jData=<json>&jKey=<token>`, with `&` in the JSON escaped as `&`, because Noren splits the body on the ampersand before parsing the JSON, so a symbol such as `M&M` would otherwise end the field early.
- Kotak's host comes from `base_url` in its stored login, normalized the way `KotakAPI.url` does it.
- Wisdom Capital is sent with certificate verification off, as its API class does, because its certificate does not match its host.
- Groww's `order_reference_id` must be 8 to 20 characters with at most two hyphens, which is why it is the tag's first seven characters, a hyphen and twelve hex digits.

## How outcomes are decided

An HTTP status below 500 at or above 300 is `rejected`, because the broker validated and refused the request. A 5xx is `unknown`, unless the broker's error code is one the removed code treated as a settled refusal, such as Kite's `OrderException` or Groww's `GA004`. A 2xx with a refusal in its body, such as Noren's `stat` of `Not_Ok`, is `rejected`. A 2xx with no order id is `unknown`. A connect timeout is `rejected`, because the request never left, and any other network error is `unknown`.

## Segments that are accepted, and markets that are not yet taken

Until 2026-09-15 only NSE and BSE cash instruments and equity and fixed income derivatives were accepted. Every removed builder had exchange codes for exactly those, and refused commodity and currency derivatives because brokers may count their quantity in lots, which had not been confirmed.

On 2026-09-15 the user asked for every segment to be enabled. The route now accepts every segment in the mapping's vocabulary on all four exchanges except the indices, which cannot be traded, and `uncategorised`, whose segment says nothing about which exchange code to send. Opening a segment at the route and opening it at a broker are kept apart: `Instrument.market()` gives `(exchange, asset class, kind)`, each broker's `MARKETS` lists the markets it takes with their codes, and `place_skip_reason` passes a broker over for any other market before looking at anything else.

The same day the user asked for the lot size problem to be settled at the start of the day. A currency or commodity order therefore takes its lot size only from the morning's decision in `unified.contract_sizes`, which the warm copies to `unified:catalogue:<date>:contract_sizes` and which rides in the same pipeline as the identity and order handles, so it adds no round trip. `check_contract_size` refuses such an order with 503 when the decision is missing or not tradeable, and with 400 when the quantity or disclosed quantity is not a whole number of lots; it runs before a broker is chosen, because the answer does not depend on the broker. The chosen broker's own lot size check stays for securities only, where the brokers agree.

How a broker's order API counts quantity on these markets is a per-broker fact kept in `QUANTITY_UNITS`, and a currency or commodity market listed in `MARKETS` without an entry there passes the broker over, so a market cannot be opened by listing its code alone. `order_quantities` converts the route's quotation units into lots, keeps them as units, or multiplies lots by the broker's own lot size, and `PlaceOrderRequest.with_quantities` hands the builder a copy carrying the converted figures, so no builder changed. No broker lists these markets yet; the user chose to confirm each broker's convention from its documentation and then with one small order before listing it. The conversion is exercised by `test_runs/order_routes.py` scenarios that add a listing to a broker's class for one scenario only.

## The midnight gap

The `unified:catalogue:` keys expire at midnight and are warmed after the 07:45 mapping, so the endpoint refuses every order in between. Falling back to PostgreSQL would break the rule that an order never waits on the database. This is recorded in `docs/contributing/known-issues.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/known-issues.md`).

## Why Stoxkart's Algo-ID goes in a header

SEBI's framework requires every API order to carry an exchange-issued Algo-ID. Stoxkart's API key for this account is approved under the non-registered strategy `NSE-BSE_NON_REGISTERED`, whose code is `99999`. On 2026-09-15 Stoxkart refused every order that carried the code only in the JSON body as `algo_id` - as `"99999"`, as the number `99999`, as `"9999999999999999"` and as the strategy name, on both `openapi.stoxkart.com` and `openapi-v2.stoxkart.com` - with HTTP 400 `invalid algo_id`. The same order with an `X-Algo-Id: 99999` header passed the check, with or without the body field, and was rejected only by Stoxkart's risk system because the market had closed. Headers named `algo-id` or `algo_id` were refused. Stoxkart's documentation mentions neither the field nor the header.

`place` therefore sends `X-Algo-Id: 99999` and keeps `algo_id` in the body too, set to the same code instead of the `"0"` it sent before. The same evening two after-market KWIL orders, one on NSE and one on BSE, were accepted by Stoxkart with the header and `99999`, so BSE needs no separate code. SEBI's framework also covers modifications and cancellations, so `cancel` sends the same `X-Algo-Id: 99999` header on Stoxkart's `DELETE /orders/{variety}/{order_id}`. Both after-market orders were then cancelled through `DELETE /api/orders/cancel`, which Stoxkart answered with `Order Submitted For Cancellation` in about 178 ms, and its order book showed `AMO CANCELLED` with nothing traded.

## Why Stoxkart's cancel reads `variety` beside `data`

Stoxkart's cancel path names the order's variety, `/orders/normal/{order_id}` or `/orders/amo/{order_id}`. The order book row carries it as `variety`, but the order socket's updates for the two after-market orders said `NORMAL`. Had a socket update been the latest write to `stoxkart:orders:orders` when the order was cancelled, the cancel would have gone to the wrong path. The raw row stays as Stoxkart sent it, so both Stoxkart order scripts store the resolved variety as a top-level `variety` in the entry, and `cancel` reads that first, then `data.variety`, then `normal`.

## How `cancel` finds the broker

A cancel names only the broker's order id, so the method has to work out which broker holds it. Three ways were weighed with the user on 2026-09-15: look the id up in the `<broker>:orders:orders` hashes that the order scripts already keep, record each order's broker when `place` sends it, or both. The user chose the hashes. They need no change to `place`, and they also hold orders placed outside the API, such as from a broker's own app. The cost is that an order is found only after a poll or a websocket update has recorded it. A Stoxkart order is found once `bin/stoxkart/orders/websocket_order_details` or `bin/stoxkart/orders/api_order_details`, which polls once a second, has recorded it.

The lookup is one pipeline: the API token, `HMGET last_login` and `HMGET settings` for all ten brokers, and one `HGET <broker>:orders:orders <order_id>` per broker. The id is looked up at every broker rather than guessed from its shape, because Flattrade's and Shoonya's ids have the same shape, the date followed by eight digits. When two brokers hold the id the method answers `409` and asks for `broker`, rather than cancelling at either.

Because the order id is sent before the token is checked, a malformed `order_id` is answered `400` before a wrong token is answered `401`. A missing `access-token` header is still answered `401` first, before any parameter is read.

## Values a cancel needs besides the order id

Six brokers need a second value, and the method reads it from the broker's own copy of the order under `data` in the hash entry, instead of fetching the order book as the removed code did, which would have cost a second broker call.

| Broker | Value | When the stored order lacks it |
| --- | --- | --- |
| Zerodha | `variety`, such as `regular` or `amo` | `regular`. Kite's postback carries `variety`, so the websocket entry has it too. |
| Stoxkart | `variety`, lowercased, because Stoxkart's order book spells it `NORMAL`, `AMO` or `BO` while its cancel path is `/orders/normal/{order_id}` | `normal`, as the removed code did. `bin/stoxkart/orders/api_order_details` has recorded Stoxkart orders since 2026-09-15, and two after-market Stoxkart orders were cancelled through the API that evening, as the section on Stoxkart's `X-Algo-Id` header above describes. |
| Groww | `segment`, `CASH` or `FNO` | Answered `503`. Groww's websocket update, `orderDetailUpdateDto`, carries no segment, and a wrong segment would only be refused, so the method waits for the next poll to replace the entry rather than guess. |
| INDmoney | `segment`, `EQUITY` or `DERIVATIVE` | Guessed from the id. Live equity ids look like `EQ-100072817`; the `DRV` prefix for derivatives comes from the older cancel code and has not been seen live. |
| Wisdom Capital | `OrderUniqueIdentifier` | `ubi`, the value `place` sends when there is no tag. |
| Kotak | `ordGenTp`, which is `AMO` for an after-market order and sets `am` to `YES` | `NO`. |

Kotak's `am` was at first always `NO`, copied from the removed `build_cancel`. On 2026-09-15 Kotak refused that cancel of a live after-market order with `hash error`, and accepted it with `YES`, so the cancel now reads Kotak's order book field `ordGenTp`, which is `AMO` for such an order.

A finished order, one whose stored status is `COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED`, is refused without calling the broker, because those statuses never change back. An `OPEN` status may be half a second stale, so an order that has just filled is still sent, and the broker refuses it.

## How cancel outcomes are decided

The rules are those of `place`, simplified. An HTTP status from 300 to 499 is `rejected`, and a 5xx is `unknown`. The per-broker lists of error codes that `place` treats as settled refusals on a 5xx were left out, because an unknown cancel costs the caller only a look at the order book, whereas an unknown placement risks a duplicate order. A 2xx whose body carries a refusal, in the same fields `place` reads, is `rejected`, and any other 2xx is `accepted`, since a cancel's response has no order id to wait for. `accepted` means the broker took the request, not that the exchange has cancelled the order.

## How `cancel` was checked

On 2026-09-15 the method was run in-process with the Flask test client against Redis database 15, filled with made-up logins, settings and orders and emptied afterwards, with `requests.Session.request` stubbed. The checks covered a dry run for each of the ten brokers, every refusal before the broker call, the two-broker `409`, the Groww `503`, and accepted, rejected and unknown answers from stubbed responses and timeouts. Those checks sent no cancel to a live broker. The first live cancels, of two Stoxkart after-market orders, followed the same evening, and the round of place, modify and cancel described below confirmed cancels at Dhan, Flattrade, INDmoney, Kotak, Shoonya, Stoxkart and Zerodha.

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

## How `modify` was designed

On 2026-09-15, straight after the place and cancel refactor, the user asked for a route to modify an order that follows that refactor. An earlier `PUT /api/orders/modify` was removed in commit 4cc8c91. It fetched the broker's live order book before every modification, which is a second broker call, and it checked neither lots nor ticks; none of its requests had been sent live. The new route keeps the rules of the other two: every Redis read is in this module, broker classes only build requests, nothing is retried, and a refusal before the broker call is a `RefusedRequestError`.

The order is found as `cancel` finds it, in the `<broker>:orders:orders` hashes. That hash also supplies every value the caller does not change, because most brokers' modify requests restate the whole order. Values are read from the normalized `order` rather than from the broker's `data`, because a websocket write replaces the whole entry and several brokers' websockets name the raw fields differently from their order books. Only values that exist nowhere else are read from `data`, as `cancel` reads them: Zerodha's and Stoxkart's variety, Groww's and INDmoney's segment, Wisdom Capital's `OrderUniqueIdentifier` and Kotak's `trdSym`.

### Why the quantity is in units, and how the instrument is found

Three meanings for a new `quantity` were weighed with the user: units found automatically, units with the caller naming the `instrument_id`, and the broker's own quantity as `GET /details` shows it. The user chose units found automatically, so a modification means the same as a placement and cannot send an order a hundred times too large at a broker that counts lots. The stored quantity is in the broker's own terms, because orders are stored as the broker sent them, and it carries no `instrument_id`, so the instrument has to be found before a changed quantity can be converted.

`resolve_order_instrument` reads `unified:catalogue:<date>:tokens:<broker>` for the stored `instrument_token` and then the candidates' identity, handles and contract size, both through `InstrumentCache`. The token hash is built from the same `broker_mappings.broker_token` column as the order handles, so matching the handle's token picks nothing out on its own. The real ambiguity is the exchange: Dhan, Noren, Stoxkart, Kotak, XTS and INDmoney number tokens per exchange segment, and Flattrade, Dhan and Stoxkart share one numbering, so one token can name an NSE and a BSE instrument. Candidates are therefore narrowed by `stored_exchange_matches`, which compares the market's code in `MARKETS` with the stored exchange, except at Fyers, Groww and INDmoney, whose order scripts store the bare exchange. The instrument counts as found only when exactly one candidate is left, because picking the first by tie-break could convert a quantity with the wrong lot size.

When the instrument is not found, a price, order type or validity change is still sent without the tick check, and a quantity change is refused unless the broker takes only securities markets, where units are the broker's terms. A Redis failure while finding the instrument answers `503` rather than counting as not found, so a Redis fault can never silently skip the checks.

### Contract sizes, and which checks apply

The user chose that a currency or commodity order whose contract size is not trusted today may still change its price, order type or validity, and only a quantity change needs the trusted size, because only the quantity is converted. Lot checks apply only to the quantities the caller changed, and the tick check only to the prices the caller gave, since a stored value was accepted by the broker already.

### How the changes are laid over the stored order

A stored price is carried over only when the order type after the change takes it and the stored order type took it too. The first rule means a change from `SL` to `LIMIT` drops the trigger price instead of being refused with "a LIMIT order takes no trigger_price". The second means a change from `LIMIT` to `SL` without a trigger price is answered `400` as the caller's mistake, instead of `503` as if Redis were missing a value. A stored product, order type or validity outside the route's words, such as a bracket order or `GTT`, is answered `409`, because the per-broker code tables have no entry for it. A stored value the request needs that is missing is answered `503`, like `cancel`'s missing Groww segment.

A disclosed quantity is compared with the quantity only after both are in the broker's terms, because one may be the caller's units and the other the stored broker quantity.

### Statuses

The same four finished statuses `cancel` refuses are refused. Restricting modifications to `PENDING` and `OPEN`, as the removed code did, was not copied, because an unrecognised status is passed through upper-cased and may still be modifiable, and the broker refuses what it will not change.

### Outcomes

A modification is decided by `decide_instruction_outcome`, the rules `cancel` uses: an HTTP status from 300 to 499 is `rejected`, a 5xx is `unknown`, and a 2xx is `accepted` unless its body carries a refusal. It does not require an order id, because several brokers' modify answers carry none or the same id, and an unknown modification costs the caller only a look at the order book. Zerodha's staff note that Kite's success answer is only an acknowledgement, and the change still passes risk checks afterwards.

## Where each broker's modify request comes from

On 2026-09-15 each broker's current modify documentation and official SDK were read before its builder was written, because the removed builders had known errors: Fyers never sent its required `type` and dropped validity silently, Kotak's used the placement keys `rt` and `pf` instead of the modify keys, and Stoxkart's sent `algo_id` as `"0"`.

| Broker | Sources | What they settled |
| --- | --- | --- |
| Zerodha | https://kite.trade/docs/connect/v3/orders/, `pykiteconnect` `connect.py`, forum threads 8292, 1661, 15306, 9231, 11945 and 15912 | Only sent fields change; quantity is the new total, and an omitted quantity leaves the pending quantity alone, so it is sent only when changed; a stop-loss order sent only a quantity was answered success and left unchanged, so prices are restated whenever the order type takes them; `market_protection` is required on MARKET and SL-M orders since April 2026 and staff said it should be set again when an order is changed to market, so `-1` is sent whenever the order is MARKET or SL-M after the change |
| Dhan | https://dhanhq.co/docs/v2/orders/, the v2 release notes, `DhanHQ-py` `_order.py` | `orderType` and `validity` are required; quantity is the placed quantity, not the pending one; `legName` is documented only for bracket and cover orders and is not sent |
| Fyers | The OpenAPI file behind `myapi.fyers.in/docsv3`, `fyers-apiv3` 3.1.17 | `type` is mandatory; limit and stop prices are needed for the types that take them; there is no validity field; whether `qty` is the total or the remaining quantity is unconfirmed, so it is sent only when changed |
| Groww | https://groww.in/trade-api/docs/curl/orders, `growwapi` 1.5.0 | `order_type` and `segment` are required and the SDK always sends `quantity`; validity and disclosed quantity cannot change; absent prices are sent as null, as the SDK does |
| INDmoney | https://api-docs.indstocks.com/normal_orders/ | `order_id`, `segment`, `qty` and `limit_price` are all required, and nothing else can change |
| Flattrade, Shoonya | https://shoonya.com/api-documentation/modify-order, https://pi.flattrade.in/docs, `NorenRestApiPy` 0.0.30 | `prd` and `trantype` are not modify fields; `exch` and `tsym` must match the order; quantity is the total; only `LMT` and `SL-LMT` can be modified to; `trgprc` must be omitted for `LMT`, because a zero trigger price is refused; the order id comes back in `result`, which `read_order_id` already reads |
| Kotak | `Kotak-Neo/Kotak-neo-api-v2` `modify_order_api.py`, and `marketcalls/openalgo` `broker/kotak`, which modifies orders in production | The path is `quick/order/vr/modify`; validity is `vd`; the token, exchange segment, symbol, side and product are restated. The keys follow OpenAlgo's production set, which leaves out the SDK's `fq`, `am` and `os`; `ts` comes from `trdSym` because the normalized symbol falls back to the underlying's name |
| Stoxkart | https://developers.stoxkart.com/api-documentation/orders, `StoxKart-Tech/superrapi-dotnet` | The body restates exchange and token but not `action` or `product_type`; the variety is in the path; the `X-Algo-Id` header is kept because placements need it, though the documentation mentions no Algo-ID |
| Wisdom Capital | https://developers.symphonyfintech.in/doc/interactive/, `xts-pythonclient-api-sdk` `Connect.py` | Every `modified…` field is mandatory, so the whole order is restated |

## How `modify` was checked

`python -m test_runs.order_routes` gained 155 modify scenarios on 2026-09-15, recorded only after a run showed every one as `NEW` and none of the 457 existing scenarios as `CHANGED`. They cover the parameters, finding the order, what each broker can change, laying changes over the stored order, finding the instrument through a token that names instruments on two exchanges, converting commodity quantities at a lots broker and a lot-size broker, an untrusted contract size, Redis failures in each round trip, a repeat that the worker's cache answers in one round trip, and a dry run and every kind of answer at every broker. The answer scenarios give the same status, outcome and message as the matching cancel scenarios.

The same evening, at the user's request and with their approval before each order, the branch's routes were run in-process from a scratchpad helper against the live Redis, with every broker but Stoxkart excluded through `api_configuration`, because the running API still had the code without the route and reloading it would have put unmerged code live. Stoxkart after-market order `526091532861`, one NSE KWIL share at ₹33, was modified to ₹32.50 and then to two shares, and cancelled. Stoxkart answered each modification `Order Submitted For Modification` in about 185 ms, its order book in Redis showed each change within a second, and the order ended `AMO CANCELLED` with nothing filled. The modifications were sent with Stoxkart's `X-Algo-Id` header, so whether a modification needs it is still unknown, and the quantity question, total or pending after a partial fill, could not be answered on an order that never filled.

## The live round at every broker

Later that evening the user asked for one round of place, modify and cancel at every broker, and gave permission to run it without asking before each order. A scratchpad helper ran the round in-process at one broker at a time, with every other broker excluded, on an after-market NSE buy of one KWIL share at ₹33, near ₹41 in the market, and checked each change in Redis before the next step. The results, and each broker's refusal, are in `docs/contributing/known-issues.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/known-issues.md`) and `docs/contributing/pitfalls.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/pitfalls.md`).

The round changed three things in the code:

- **Side, product and validity may be missing.** INDmoney's order book stores `validity` as an empty string, so every INDmoney modification was answered `503`, although INDmoney's modify request sends no validity; and a Shoonya quantity change was answered `503` because the entry, most likely written by Shoonya's order websocket after the price change, had no product, although Noren's modify request sends no product. `OrderModification` therefore reads these three as optional, still answering `409` for a word outside the route's vocabulary, and each builder that sends one refuses a missing value through `BrokerOrders.stored_value`. The order type stays required, because every builder and the price rules use it.
- **Kotak's cancel reads `ordGenTp`**, as the cancel section above describes.
- **Test prices stay inside the price band.** The first Zerodha price change, to ₹32.50, was refused as below the lower circuit limit, so the helper moved to ₹33.50, and Zerodha's round was run again and passed.

The rounds at INDmoney, Shoonya, Kotak and Zerodha were run a second time after the fixes, and every step passed. Every test order ended cancelled with nothing filled.

## Why Zerodha's MARKET and SL-M orders carry `market_protection`

When the modify route's sources were read on 2026-09-15, Kite's forum thread 15912 showed that since 1 April 2026 Kite refuses a MARKET or SL-M order sent through its API without a non-zero `market_protection`. Staff wrote on 27 March that market orders "must include a non-zero market protection value, otherwise they will be rejected starting April 1", that this includes SL-M orders, and on 1 April that it applies to MCX contracts; users quoted the refusal `Market orders without market protection are not allowed via API. Please set market protection or use a Limit order`. The place request had been copied from code written before the rule, so every Zerodha MARKET and SL-M order through the API would have been refused. The earlier live placements were all LIMIT orders, which is why nothing showed it.

At the user's request the same evening, `build_place_request` sends `market_protection=-1` on MARKET and SL-M orders, and `build_modify_request` sends it whenever the order is MARKET or SL-M after the change, not only when the type changes, so a trigger price change on an SL-M order restates it. `-1` asks Zerodha for its automatic protection, as the documentation's own example sends; a fixed percentage from 1 to 100 was not chosen, because the right band differs by instrument and Zerodha's automatic value follows the exchange's. Kite says the field has no effect on LIMIT and SL orders, so it is not sent on them, which left every recorded LIMIT and SL scenario unchanged.

At 23:25 IST the same evening, with the user's permission, the branch's routes placed an after-market MARKET buy of one KWIL share at Zerodha with `market_protection=-1`, in-process against the live Redis with every other broker excluded. Kite accepted it as order `2099920159803219968` in 79 ms, and its order book stored it as a LIMIT order at ₹41.65, about 1% above the last price, with `market_protection` 0: Zerodha applies the protection by converting the order to a limit order at the band's edge. The helper had planned a quantity change that expected `market_protection` in the modify request, and skipped it because the stored order was now LIMIT, which is the route behaving correctly. The order was cancelled in 46 ms and ended `CANCELLED` with nothing filled. An SL-M order has not been placed with the field.


## Why flatten names the broker in engine mode, and why `place` removes it

On 2026-09-26 a review from the sridhara project found that `POST /api/orders/flatten` sent its closing orders to the wrong brokers when `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` was `engine`. The route worked out correctly which broker held each position and put that broker in the intent's body as `broker`, but the engine ran each close as a plain `simple` order, and `SimpleOrder` called `place_leg` without a broker, so the round-robin selector chose one. A SELL meant to close a long position at Zerodha could land at Dhan, leave the Zerodha position open and open a new short at Dhan. The merged positions document would then show the two cancelling out, and the route answered `"flat": true` because every close was accepted.

The fix has three parts, made together because each one alone is unsafe:

| Part | Where | Why it is needed |
| --- | --- | --- |
| `SimpleOrder` sends to `body['broker']` when it is set | `unified_broker_interface/utilities/order_engine/simple.py` | This is the actual fix. |
| `place` removes `broker` from the caller's body before the handoff | `place_order` in this module | The engine carries the caller's body verbatim, so without this any caller of `/place` could steer an order to a broker of their choosing. UBI is meant to be the only broker its callers see. |
| Flatten's engine body adds `"synthetic": {"type": "simple", "closes_position": true}` | `place_closing_order` in this module | Without it a close near a broker's daily order cap was judged as a new entry and could be refused while the exit reserve was still free. |

The same review claimed that OCO, ladder, grid, basket, square-off and two-sided breakout already read a caller's `broker`. They do not: the `body.get('broker')` in those types reads the broker's answer to their first leg, so later legs follow the first. There was no existing side door to close.

The removal is inline in `place_order` rather than in `PlaceOrderRequest`, because the validated request is never what reaches the engine; the raw body is.

## Why flatten re-reads the positions before saying `flat`

The same review found that flatten's `flat` meant only that every close had been accepted. A broker can accept an order that the exchange then rejects, and in the routing bug above every close was accepted while the position stayed open, so `flat` was true in exactly the case it most needed to be false. Since 2026-09-26 the route re-reads every broker's `<broker>:portfolio:positions` after the closes, in the same way it re-reads the order books after the cancels, and `flat` is true only once every accepted close shows its position at zero.

The second wait reuses `UNIFIED_BROKER_INTERFACE_API_ORDER_FLATTEN_WAIT_SECONDS` rather than adding a setting, because both waits are for the same thing: a poller writing what the broker now reports. Nine positions pollers refresh every 0.5 or 1 second; Fyers's refreshes every 5 seconds, so a Fyers position closed late in the wait can be reported as still held. That is a false alarm on the safe side, and the answer says so rather than claiming a flat account it has not seen.

Only closes the broker accepted are waited for. A close that was not sent or was refused is already a failure, and waiting for its position would hold the answer for the whole wait without changing it.
