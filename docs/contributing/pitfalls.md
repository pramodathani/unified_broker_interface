# Pitfalls

Every entry on this page passed code review and then failed against the live system. They are
recorded because each one is invisible in the code that causes it - the wrong version reads as
correct, and only running it against a real broker says otherwise. All of them are fixed; the point
is not to write them again.

## Shutdown and restarts

**A drain loop must count rows read, not rows written.** A persister whose drain step returns the
number of rows it persisted sees a final batch of unusable records as an empty queue and exits the
loop - leaving the usable rows queued behind them, which are then never written at all. The loop
condition is "did I take anything off the queue", not "did I store anything".

**Signal handlers have to be installed before the threads start.** A `join()` with correct SIGTERM
handling is never reached when the entry point starts its threads first. Install the handlers, then start the
threads.

**`.venv/bin/python` is a symlink to the system interpreter.** The `bin/` commands re-exec
themselves under the virtualenv, and a guard that decides whether the re-exec already happened
by comparing resolved interpreter paths finds them equal, so the switch silently never happens and
the commands run against system site-packages. Compare `sys.prefix`.

**A store that is still starting is not a dead session.** After a reboot the seven
`<broker>-historical-prices.service` units started while Redis was still reading its saved dataset back
from disk. Redis refuses every ordinary command with `BusyLoadingError` until it has finished, the
worker's first login reads the stored token out of Redis, and each one logged `Could not log in to
<Broker>: BusyLoadingError: Redis is loading the dataset in memory` and exited 2 - which the units read
as a bad configuration and would not restart, so all seven stayed down until someone ran
`bin/check-services`. It happened on 2026-09-18 and again on 2026-09-22, before
`ExecStartPre=%h/Projects/unified_broker_interface/bin/wait-for-redis` was put in front of them and
`RestartPreventExitStatus=2` was dropped. A temporary refusal from a store that has not finished
starting reads exactly like a broker refusing a session, and only a real reboot tells the two apart.

## Sessions and logins

**A login attempt is not a login success.** A rate limiter keyed off a single
marker lets a login unit record an attempt and makes every script starting a second later hit the limiter
and sleep for 299 seconds before doing anything. The usual outcome of `ensure_session` is a cheap probe
that writes nothing to MongoDB, so an attempt marker alone cannot tell "the probe succeeded" from "the
login failed". `ensure_session` keeps two markers, `ubi:login-attempt:<broker>` and
`ubi:login-ok:<broker>`, and only genuine retries are rate limited.

**A lock holder that died still holds the lock.** Killing a process inside `ensure_session` -
before its own signal handlers exist - leaves `ubi:login:<broker>` held for its full 300 second TTL,
and every other process waits it out. The lock records the holder's pid, and a lock whose pid is gone is
released rather than waited for. `ensure_session` is what `BrokerCandles` and IND Money's instrument
ingester log in through by default; the `bin/<broker>/` scripts log in through the broker's API class.

**An error code prefix is not a diagnosis.** Wisdom Capital's quotes feed classified a refusal by looking
for `e-session` in the body, and XTS answers instruments that are still subscribed from an earlier
connection with `{"code":"e-session-0002","description":"Instrument Already Subscribed !","result":
{"Remaining_Subscription_Count":45}}` - a code carrying that prefix, alongside a result that shows the
request plainly authenticated. On the restart at 22:19:13 on 2026-09-22 the feed read that as a dead token
and minted a new market data session, which invalidated the token the candle downloader was using in the
same second, so both had to log in again to recover. XTS issues one market data session per application
key, so throwing a good token away is never local to one process. The feed now drops the stale
subscription with `PUT /apimarketdata/instruments/subscription` and asks again, and only treats the answer
as a refused token if that fails too.

**Stoxkart's documented login stops at the TOTP.** Once the API app was approved, `/auth/login` accepted
the password and asked for a TOTP, but `/auth/twofa/verify` answered every attempt with HTTP 400 and a
body of only `{"status":"error"}`. Stoxkart's documentation does not describe the TOTP step at all.
Its own login page had moved to `/auth/v2/login` and `/auth/v2/twofa/verify`, which carry the client id,
password and TOTP in headers alongside a publisher key pair that is separate from the app's key, and
that flow worked first time on 2026-09-15. The pair lives in the `stoxkart` settings document as
`publisher_api_key` and `publisher_api_secret`; if the login starts failing again, compare it with the
pair in the current JavaScript of `superrtrade.stoxkart.com/login`.

**Changing Stoxkart's API key must keep the publisher key pair.** When the settings document was updated
for a new API key on 2026-09-15, `publisher_api_key` and `publisher_api_secret` were lost, and every
Stoxkart login failed until the old pair was put back. The pair comes from Stoxkart's login page rather
than from the API app, and the old pair works with the new key, so only the app's own key changes.

## Placing and cancelling orders

**Stoxkart takes its Algo-ID only as an `X-Algo-Id` header.** SEBI's framework for retail algorithmic
trading requires an exchange-issued Algo-ID on every order sent through an API. Stoxkart refused every
test order with HTTP 400 and `{"message":"invalid algo_id","status":"failed","code":"ValidationError"}`,
first while the body carried no `algo_id` or `"algo_id": "0"`, and then even after the API key was moved
from the app "Test1234", approved for the strategy `BSE_NON_REGISTERED` with the code `9999999999999999`
on BSE only, to the app "Test App" (#30), approved for the non-registered strategy
`NSE-BSE_NON_REGISTERED` with the code `99999`, with the host's static IPs registered under My API
Requests on `developers.stoxkart.com`. With that app, the body's `algo_id` was still refused as the
string `"99999"`, as the number `99999`, as `"9999999999999999"` and as the strategy name, on both
`openapi.stoxkart.com` and `openapi-v2.stoxkart.com`. An order passed the Algo-ID check only when the
code was sent as the HTTP header `X-Algo-Id: 99999`, and headers named `algo-id` or `algo_id` were
refused. Stoxkart's documentation does not mention the header. `POST /api/orders/place` now
sends the header together with `"algo_id": "99999"` in the body, BSE orders accept the same code, and
`PUT /api/orders/modify` and `DELETE /api/orders/cancel` send the same header on Stoxkart's modify and cancel.

**Stoxkart's order socket reports an after-market order's variety as `NORMAL`.** Stoxkart's cancel URL
names the order's variety, as in `DELETE /orders/amo/{order_id}`. On 2026-09-15 the order book said
`AMO` for two after-market orders, but the socket's cancellation updates for the same orders said
`variety: NORMAL`, so a cancel built from the newest socket update would name the wrong variety. Each
entry in `stoxkart:orders:orders` therefore carries a top-level `variety` beside `data`. The poller
copies the order book row's variety, and `bin/stoxkart/orders/websocket_order_details` keeps an `AMO` or `BO` variety
already stored, reads `AMO` from a status starting with `AMO`, and uses the update's own variety only
otherwise.

**Kotak refuses to cancel an after-market order sent with `am` of `NO`.** On 2026-09-15 Kotak accepted an
after-market order, two modifications of it and nothing else: the cancel, sent with `"am": "NO"` as the removed
cancel code sent it, came back with `stCode` 14, `error from core` and `ErrorCode(16) -> ErrorText(hash error)`,
which says nothing about the flag. The same cancel with `"am": "YES"` was accepted. Kotak's order book marks
such an order `ordGenTp: "AMO"`, which the cancel now reads. Its modification needed no after-market flag.

**Dhan refuses to modify an after-market order after hours, but cancels it.** On 2026-09-15 at 22:55 IST Dhan
accepted an after-market order, refused both a price and a quantity modification with `DH-906`
`Market is Closed! You cannot modify/cancel an order now.`, and then accepted a cancel of the same order a
second later, despite the message. A modification has to be tried during market hours.

**Fyers takes no after-market orders through its API.** An order with `offlineOrder: true` was refused with
`AMO order placement is not supported via API.`, so outside market hours nothing can be placed at Fyers to
modify.

**Zerodha checks an after-market modification against the circuit limits.** Kite accepted an after-market buy of
KWIL at ₹33 but refused a modification to ₹32.50, below the lower circuit limit of ₹32.67, with an
`InputException`, while Stoxkart accepted the same price that evening. Test prices far from the market must stay
inside the day's price band.

**Zerodha turns a market-protected MARKET order into a LIMIT order.** Since April 2026 Kite refuses API market
orders without a non-zero `market_protection`. On 2026-09-15 an after-market MARKET buy of one KWIL share sent with
`market_protection=-1` was accepted, but Zerodha's order book stored it as `order_type` `LIMIT` at ₹41.65, about 1%
above the last price, with `market_protection` 0. A script that expects the order to stay `MARKET` after placing it
will be wrong: the stored order, `GET /api/orders/details` and any modification see a limit order.

## The candle queue

**The backward walk has to finish before any forward fill.** Preferring a forward fill whenever
the newest stored bar is older than today is reasonable-looking and deadlocks: outside market
hours the newest bar is always older than today, so the series re-asks the same empty recent
window forever and never walks back. See
[Walking backwards, then forwards](../guides/price-history.md#walking-backwards-then-forwards).

**Finishing a backfill is not retiring a series.** Reaching the broker's earliest date means
there is no more past, not that the instrument is dead - the series must keep collecting forward.
`_finish_backfill` and `_retire` are separate for that reason.

**A throttle says nothing about the series.** Recording each of Dhan's refusals as a series failure
pushes perfectly good series an hour into the future for something that is purely about the pace. A
throttle backs the rate limiter off and leaves the series claimable.
Dhan refuses five requests a second whatever its documentation says: twenty five requests at five
a second were throttled four times, at three a second none were.

**A broker can send the same bar time twice in one window.** Dhan does, and Postgres refuses a
batch that touches the same row twice - `ON CONFLICT DO UPDATE command cannot affect row a second
time`. The exception came out of `_store`, past `visit`, and ended the run. Bars are collapsed on
time before the write, last one winning.

**The write has to be inside the per-series guard too.** `visit` guarded the fetch and the parse
but not the store, so the failure above took the whole process down - and because the same window
is claimed again on restart, it would have taken it down every ten minutes for as long as the
service stayed enabled. An unexpected failure costs the series, not the run.

**A single impossible count fails the whole window, every time.** Kite sent volumes above
2⁶³ − 1 for a handful of 2023 intraday bars, Postgres refused the batch with
`bigint out of range`, and the window rolled back. Because the next attempt asks for the same
window, the series never moved again - 77 of them stopped at the same July 2024 boundary, while the
parser tests passed, since they never see such a value. Counts outside the `BIGINT` range are stored
as `NULL` with a warning; see [Known issues](known-issues.md#observations-stored-as-received).

## Writing to the database

**`execute_values` pages internally, so `cursor.rowcount` reports only the last page.** A seed
that registered 1,149,064 rows announced itself as having written 22,964. Count what was passed
in, not what the cursor says afterwards.

**Chunk size is measured, not guessed.** Seven day chunks for `price_history` put two decades of
one instrument's daily bars across 1,133 chunks of 98 rows each, where the per-chunk overhead
dwarfed the data: 75 MB for 111,000 bars, against 35 MB for the same data in one month chunks.

## Feeds, one refusal per broker

Every one of these is a broker refusing a connection in a way that reads as something else, and none
of them shows up while only Zerodha is tested.

**A token is not always a number.** Only Zerodha's subscription tokens are integers; every other broker
carries a segment - `NSE_EQ:2885`, `NSE|2885`, `NSE|CASH|2885`, `1:2885`, `NSE:SBIN-EQ` - so a feed that
discards every token it cannot parse as an integer starts, subscribes to nothing, and exits quietly at
nine of the ten brokers.

**Noren's connect frame is `t` of `a` and the token is named `accesstoken`.** Sending `t` of `c`
with the token as `susertoken` is parsed and refused with `NOT_OK`, which is indistinguishable
from an expired session and is not one - the same token authenticates REST happily. Verified
against both Flattrade and Shoonya.

**Kotak's `sfeed` answers a subscription with one stale snapshot and then nothing.** Until 2026-09-15
`bin/kotak/instruments/websocket_quotes` used `wss://sfeed.kotaksecurities.com/apifeed`, which authenticated, acknowledged the
subscription, sent one snapshot and stayed connected without a further tick. The snapshot carried
Friday's prices with zero volume, and more arrived only at session boundaries, so the stream held a few
dozen ticks a day and looked like a quiet feed rather than a broken one. In the same minute the HSM feed
of Kotak's SDK, `wss://mlhsm.kotaksecurities.com`, updated every instrument every second. Before trusting
a feed, compare its last price and volume with another broker's during the session.

**Kotak's HSM feed asks for acknowledgements.** Its connection reply carries a count (five on
2026-09-15), and every data frame then starts with a message number; after that many frames the client
must send an acknowledgement frame with the last number. A decoder that does not expect the message
number reads it as the packet count.

**Kotak's MCX quantities are all in Kotak's lots.** On the HSM feed volume, open interest, total buy and
sell quantity, last quantity and every order book quantity are lots times Kotak's own lot size - 100 for
CRUDEOIL, 1250 for NATURALGAS, 1 for GOLD, whose 1 kg contract Kotak counts in kilograms. GOLD alone therefore looks
like plain lots, which is how the older feed's figures were misread.

**Kotak spells a successful `stat` as `ok` on some paths.** The `kotak_request` helper in every
`bin/kotak/` REST script accepted only a `stat` of `Ok`, or no `stat` at all. The positions and trades
paths answer `{"stat": "ok", "stCode": 200, "data": [...]}`, so every successful answer that carried rows
was raised as `KotakAPIException: (200, "{'stat': 'ok', ...")`, logged as a failed poll and thrown away.
An empty book never reached the check, because Kotak answers it with `stCode` 5203 ("No Data"), so the
scripts looked healthy until the first trade of 2026-09-15 filled at 12:03. `kotak:portfolio:positions`
and `kotak:orders:trades` then stayed stale for four hours while their services kept running; orders,
funds and holdings kept working. The helpers now compare `stat` without regard to letter case. Test a
Kotak poller with a non-empty book before trusting it.

**Wisdom Capital's interactive socket needs `apiType=INTERACTIVE` in its socket.io query.**
Without it the namespace answers "Socket joined successfully!" and the server closes the
connection exactly ten seconds later, every time, at every heartbeat rate and with every user
identifier the login offers. The "Your session has been expired" that arrives alongside the join
is noise - it appears for a token minted a second earlier.

**INDmoney's price feed sends JSON inside a JSON string.** Every update is a line such as
`"{\"mode\":\"full\",\"instrument\":\"11536\",...}"`, so one `json.loads` returns a `str`. `bin/indmoney/instruments/websocket_quotes`
treated anything that was not a dict as a heartbeat and skipped it quietly, and for at least the five days to
2026-09-15 the feed connected, subscribed and streamed about ten updates a second while `indmoney.ticks` stayed
empty. Decode a string result a second time, and log a message you skip rather than dropping it silently.

**INDmoney's `close` is the last price.** In `quote` and `full` mode the feed's `close` moves with every trade and
equals `ltp`; the previous close is not on the feed at all. `quote` mode has no `ltp`, which made `close` look like
the only price.

**Wisdom Capital's interactive socket must not log in for itself.** XTS keeps one interactive session per
application key, so a login by the socket logged out the token the pollers share, the pollers logged in again, and
their login logged out the socket. The socket then received `logout` ("You have been logged out by another user.")
and stayed connected while delivering nothing, which looks exactly like a quiet account. From 2026-09-14 to
2026-09-15 it merged no updates at all. It now joins with the shared `last_login` token, taking the user id from the
token's payload, and treats `logout` as a reason to reconnect with whatever login replaced it.

**XTS states two heartbeat numbers and they disagree.** The server says how often it wants to
hear from us and how long it will wait, and market data asks every 20s while waiting 60s where
interactive asks every 25s but waits only 20s. Pacing on `pingInterval` alone heartbeats every
23s into a 20s patience. Use half the shorter of the two.

**Stoxkart's documented quote websocket is dead.** Stoxkart's documentation gives a binary quote feed at
`ws://inmob.stoxkart.com:7763`. On 2026-09-15 that port refused every connection, and the same host on port
443 answered the websocket handshake with HTTP 503 from an AWS load balancer with nothing behind it. Two
other names were tried the same day and failed too: `superapi.stoxkart.com` has no DNS record, and
`superrapi.stoxkart.com` is the Superr marketing site, whose websocket handshakes timed out on every path
tried and whose ports 7763, 9443, 9444 and 9964 are closed.

**Stoxkart's working quote feed is not the documented one.** Stoxkart's own trading website,
`webtrade.stoxkart.com`, streams quotes from `wss://broadcasting-v2.stoxkart.com/` on port 443, which was
found by watching the website in Chrome DevTools. It is a different host from the API documentation's, it
takes a blank token, and it subscribes with request codes 12 (trade) and 23 (depth) rather than the
documented 71 to 76, so a script written from the documentation alone gets nothing from it.
`bin/stoxkart/instruments/websocket_quotes` sends what the website sends.

**Stoxkart's order socket evicts the older connection.** Stoxkart keeps one order socket per client, and a
new connection closes the older one with a close reason containing `new incoming connection`. A logged-in
Stoxkart website or app therefore knocks `bin/stoxkart/orders/websocket_order_details` off, and a script that reconnects at
once knocks the person off in turn, over and over. The script waits five minutes before reclaiming the
socket. The socket's authentication must also send `x-platform: api`, because the same API token with
`x-platform: web` is refused with `AuthorizationError`.

**Stoxkart counts `last_trade_time` from 1980, not 1970.** Its `last_trade_time` is a count of seconds
from 1980-01-01 UTC, so read as a Unix time it lands ten years in the past and still looks like a
plausible timestamp. `bin/stoxkart/instruments/websocket_quotes` adds 315532800 seconds, and the converted time matched
Zerodha's last trade time to the second on 2026-09-15. A value of 0 is stored as null.

## Platform notes

- `add_columnstore_policy` is a **procedure** (`CALL`); `compress_chunk` is a **function**
  (`SELECT`). Same extension, opposite conventions.
- `load_dotenv()` resolves `.env` from the module's directory rather than the working directory,
  which is why cron and systemd need no `WorkingDirectory`.
- systemd **user** units want `WantedBy=<broker>.target` or `WantedBy=unified.target`, and each
  target wants `WantedBy=default.target` - **not** `multi-user.target`, which does not exist in the
  user manager and would silently never start anything.
- `StartLimitIntervalSec=0` on every long-running unit, or a briefly unreachable Redis or a broker
  outage leaves one failed permanently. The login units are the exception on purpose: three tries an
  hour.
- A feed unit and its persister need no `After=` ordering between them: a Redis Stream keeps its
  entries, up to its cap, until the persister reads and acknowledges them, so whichever stops first
  loses nothing. See
  [Running it as a service](../guides/services.md).
- NSE and BSE equity close at 15:30 IST but **MCX trades to 23:30**, so use MCX futures to
  exercise a live feed in the evening.
- Tested against TimescaleDB 2.30, PostgreSQL 18.6, Redis 8.10.1 and Python 3.14 on Ubuntu 26.04.
