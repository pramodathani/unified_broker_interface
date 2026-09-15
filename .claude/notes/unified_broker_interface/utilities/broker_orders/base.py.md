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
