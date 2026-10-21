# Notes on `unified_broker_interface/utilities/broker_orders/base.py`

## Why there is an idle limit on order connections

On 2026-09-15 the user asked whether connections to the brokers could be kept warm, and made it a hard condition that this must never make an order fail in any case, such as a closed connection. Working through that condition showed a failure that existed before any warming: brokers' servers close idle keep-alive connections, and an order written to a pooled connection in the moment the server closes it fails with `RemoteDisconnected`, which `send` answers as `unknown` (504) although the broker never received the order. urllib3 closes a pooled connection it can see was dropped, but it cannot see a close that has not yet arrived.

`test_runs/connection_warming.py` reproduces this deterministically: a local server that drops a request arriving on a connection idle longer than 0.3 seconds makes the second of two orders 0.5 seconds apart come back `unknown` when there is no idle limit, and `accepted` on a new connection with a limit of 0.2 seconds.

`IdleLimitedAdapter`, in `utilities/connection_pool.py`, is requests' default adapter with pools that note when each connection is returned and close a connection that comes out again after more than `MAXIMUM_IDLE_SECONDS`. The closed connection object is still handed out and reconnects when the request is sent, which is exactly what urllib3's own `_get_conn` does with a dropped connection. The limit costs an occasional handshake and never an order, and it applies whether or not warming is on.

The pool subclasses override urllib3's `_get_conn` and `_put_conn`, which are private. They were chosen because they are the only place every connection passes through, and they have kept their signatures across urllib3 1.x and 2.x; `test_runs/connection_warming.py` exercises them against the installed version (urllib3 2.7.0, requests 2.34.2, on 2026-09-15). A plain-HTTP twin of the HTTPS pool exists only because the offline tests use HTTP. Return times are kept in a `WeakKeyDictionary`, because urllib3 closes and drops a connection when the pool is full without telling the pool subclass, and an ordinary dictionary would keep those connections forever.

## The measurement behind the numbers

The user approved sending requests with no login to the ten brokers' API hosts to measure this. On 2026-09-15 at about 18:30 IST, from this host, each host got three `HEAD /` requests on a new session followed by one on the same session, and then one connection was left idle until the server closed it or ten minutes passed.

| Broker | Host | Server | `HEAD /` status | Sets a cookie | New connection, ms | Open connection, ms | Idle close |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dhan | `api.dhan.co` | awselb/2.0 | 301 | no | 58, 48, 54 | 39, 42, 31 | 240 s |
| Flattrade | `piconnect.flattrade.in` | cloudflare | 200 | no | 106, 74, 77 | 39, 43, 44 | 400 s |
| Fyers | `api-t1.fyers.in` | cloudflare | 404 | yes | 92, 70, 80 | 41, 39, 43 | 400 s |
| Groww | `api.groww.in` | cloudflare | 404 | yes | 94, 79, 78 | 43, 43, 349 | 400 s |
| INDmoney | `api.indstocks.com` | cloudflare | 403 | yes | 74, 58, 62 | 23, 19, 28 | 400 s |
| Kotak | `e43.kotaksecurities.com` | not named | 503 | no | 79, 56, 55 | 23, 23, 24 | 600 s |
| Shoonya | `api.shoonya.com` | nginx | 200 | no | 97, 88, 79 | 23, 23, 23 | 65 s |
| Stoxkart | `openapi.stoxkart.com` | awselb/2.0 | 503 | no | 131, 78, 105 | 38, 28, 36 | still open at 600 s |
| Wisdom Capital | `trade.wisdomcapital.in` | nginx | 200 | no | 112, 109, 97 | 33, 37, 33 | 65 s |
| Zerodha | `api.kite.trade` | cloudflare | 405 | yes | 93, 75, 76 | 36, 43, 40 | 400 s |

Every server answered with `Connection: keep-alive` and none sent a `Keep-Alive: timeout`, so the timeouts could only be measured. Kotak's close at exactly 600 seconds, the length of the wait, is read as a 600-second timeout; it could in principle be a coincidence.

Each limit is about three quarters of the measured timeout, rounded down, and never above 300 seconds, so that a middlebox on the path with a shorter timeout than the server's is less likely to matter: 45 seconds for the 65-second nginx hosts, 180 for Dhan, and 300 for the rest. The ping interval is a third of the limit or less: 15 seconds for the nginx hosts and 60 for the rest. The base class's defaults, 30 and 20 seconds, are deliberately short for a broker added without measuring.

## How a warming ping is kept away from orders

`warm_connection` was designed around the user's hard condition, and each choice answers one way a ping could reach an order:

- It sends through the session's adapter, not the session, so it shares the order requests' connection pool but never reads or writes the session's cookie jar or headers. Four of the Cloudflare hosts set a cookie on `HEAD /`; sent through the session, that cookie would ride on every later order. The offline suite showed exactly that with a session-based ping: 195 to 199 of 200 orders carried the ping's cookie.
- It holds its connection for `WARM_SETTLE_SECONDS` after the answer and returns it to the pool only if the socket has not become readable, which for an idle keep-alive connection means the server has neither closed it nor sent anything. A server that closes a connection 30 milliseconds after answering, with an order sent straight after the ping, made 20 of 20 orders `unknown` with a ping that returned its connection at once, and 0 of 20 with the settle check.
- A ping that raises leaves cleanup to urllib3, which closes the connection on any error; `ConnectionWarmer.ping` catches every exception, since it is the isolation point between the warmer thread and the API.
- While a ping holds a connection, an order takes another from the pool or opens one, because requests' pools do not block.

Before the settle check was trusted, it was checked on the real hosts in case a TLS 1.3 session ticket arriving after the handshake made every healthy connection look readable and so be discarded. On 2026-09-15 all ten hosts' pings came back `kept` three times in a row, with the second and third 20 to 50 milliseconds faster than the first.

## Kotak's warm URL

Kotak's API host comes from `base_url` in its login (`e43.kotaksecurities.com` on 2026-09-15), and reading the login would mean reading Redis from the order classes, which the blueprint's rule forbids. `WARM_URL` is None for Kotak, and `warm_url` returns the scheme and host of the latest request sent to the broker when there has been one, so a Kotak warmer does nothing until the worker's first Kotak request and then keeps that host warm. Every broker uses the same rule, which also follows a host that changes after a new login.

## Wisdom Capital's certificate warning

Wisdom Capital's certificate does not match its host, so its requests are sent with certificate checks off, and urllib3 warns on every such request. That was tolerable for orders, but a warmer pinging every 15 seconds in two workers would write about 11,500 identical warnings a day to the service log. The constructor therefore adds a warnings filter that ignores `InsecureRequestWarning` for the broker's own `WARM_URL` host, and only for a broker that has turned certificate checks off.

## Why `MODIFIABLE_FIELDS` is empty by default

A broker class that lists no modifiable fields is answered `501` by `PUT /api/orders/modify` before anything is built. The default is empty rather than every field so that a new broker, or one whose modify request has not been written, is refused cleanly instead of reaching the base `build_modify_request` and answering `500` from `NotImplementedError`.

## Why `stored_exchange_matches` is a method

Most brokers' order scripts store the same exchange or segment code the broker's `MARKETS` lists, such as Kotak's `nse_cm` or Dhan's `NSE_EQ`, so the base method compares the two ignoring case. Fyers, Groww and INDmoney store the bare exchange, `NSE` or `BSE`, and override it to compare the instrument's exchange instead. It is a method on the broker class, rather than a table in the blueprint, because what a broker's order book stores is a fact about that broker.

## Why `modify_problem` reuses `cancel_login_problem`

A modification and a cancel both instruct the broker about an existing order with the same login, so Kotak's `sid` check applies to both, and one hook keeps the two from drifting apart.


## Settling a reset place-order request (2026-10-21)

On 21 October 2026 a live call-put switch run on Flattrade lost its protective stop: the engine sent the stop's sell at 11:33:48, the connection was reset (`ConnectionError(ProtocolError('Connection aborted.', ConnectionResetError(104)))`), the leg's outcome was `unknown`, and `OUTCOME_PARENT_STATES` turned the plan `failed` at once. The script's own exits were reset twice more before one got through at 11:34:54. The same happened to the 22850 PE's stop at 11:35:53, and to trade 6 earlier that morning, which lost ₹978. The user asked to fix the underlying issue.

Evidence gathered that day:

- Every `unknown` outcome in `unified.synthetic_order_events` over the previous 15 days was a Flattrade connection reset: 12 on 13 Oct, 14 on 19 Oct, 9 on 21 Oct.
- None of the 14 on 19 Oct appears in `unified.daily_orders` (Flattrade's own book, saved nightly) within 3 s of being sent, and none of the 9 on 21 Oct appears in the live order book. So 23 of 23 checkable reset orders never reached Flattrade. 13 Oct predates the daily snapshot and could not be checked.
- Resets came back 45 to 212 ms after sending (median 129, a few up to 4.7 s), overlapping Flattrade's normal acceptance time (median 87 ms over 1,071 orders), so latency cannot tell an unreceived order from a received one. That is why the book is read rather than resending blindly.
- The warmers in both REST workers and the engine log a Flattrade reset every few minutes, often two processes within seconds. Probes from the same machine with plain `requests` sessions (pinging every 2 s for 4 minutes; 20 connections idle 10 to 90 s for 5.5 minutes) saw no reset at all, while the engine's warmer logged one in the same window, so the cause on Flattrade's side was not pinned down. A 25-minute connection-age probe was started; see the note on `noren.py` for its result if it was recorded.

What changed:

- `BrokerAnswer.connection_reset`, set by `send` through `is_connection_reset`, which searches the wrapped error's `args` up to four levels for `ConnectionResetError`, `BrokenPipeError` or `http.client.RemoteDisconnected` (a subclass of `ConnectionResetError`, the stale keep-alive case). A `Timeout`, including `ConnectTimeout`, is never a reset.
- `send_place` calls `recover_after_reset` when nothing came back and the connection was reset. It asks `find_placed_order` (overridden by `NorenOrders`; the base answers `cannot_tell`, so every other broker is unchanged). `found` makes the answer `accepted` with the book's order id; `absent` sends once more through `send_on_fresh_connection` (a one-off `requests.Session`, so the resend cannot draw another stale pooled connection) and that answer goes through the normal decoding; `cannot_tell` keeps `unknown` and appends the reason in parentheses.
- Only one resend: a second reset stays `unknown` with "sent again, which also failed".
- `send` takes an optional `session`, used by the resend and by the book read; both still count against the daily cap through `count_message`.
- The engine places legs through `Placement.send` → `send_place`, so held stops and plan legs get the recovery too; `OUTCOME_PARENT_STATES` is unchanged, and an `unknown` that survives recovery still fails the parent.

Remaining risk, accepted: if Flattrade received an order but its `OrderBook` did not list it yet when read (about 0.1 to 0.3 s later), the resend places it twice. Noren's book is the OMS's own and none of the 23 resets had arrived, so this was judged far smaller than a stop that silently dies.

Checked by `test_runs/reset_recovery.py` (11 checks), the existing order suites (`connection_warming` 22/22, `broker_selection` 54/54, `order_routes` 620/620, `order_engine` 716/716, `order_engine_changes`, `order_place_lists`, `order_change_lists`, `order_flatten`, `margin_calculators` all matching), and `examples/.../BrokerOrders/example_5_telling_a_reset_from_a_timeout.py`.
