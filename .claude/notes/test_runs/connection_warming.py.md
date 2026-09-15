# Notes on `test_runs/connection_warming.py`

## Why the suite uses a real local server

The idle limit and the warming ping both depend on how urllib3's connection pool behaves when a server closes, resets or delays a connection. A stub of `requests.Session.request`, as `test_runs/order_routes.py` uses, would skip the pool entirely. The suite therefore runs a `ThreadingHTTPServer` on a free port of 127.0.0.1 and sends real requests through a `BrokerOrders` subclass, over plain HTTP, which is why `connection_pool.py` has an HTTP twin of its HTTPS pool.

## Checks that fail without the protection they test

On 2026-09-15 each protection was removed in turn to confirm the suite notices:

| Protection removed | What the suite reported |
| --- | --- |
| The idle limit (`None`) | The second order after a pause longer than the server's idle timeout was `unknown` (`RemoteDisconnected`). This check is kept in the suite as the demonstration of the risk. |
| The settle check (a ping returning its connection at once) | `silent_close` and `connection_close` pings reported `kept`, and an order sent straight after a `late_close` ping was `unknown` in 20 of 20 attempts |
| Pinging through the session instead of the adapter | Cookies from pings reached 195 to 199 of 200 orders, and a `silent_close` ping made an order `unknown` |

The busy test, four threads of fifty orders each while a warmer pings every five milliseconds, did not catch the missing settle check on its own, because on localhost a close usually arrives before an order takes the connection. The `late_close` check was added for that reason: the server closes the connection 30 milliseconds after answering the ping, which is longer than the time an order takes to be written to the connection and shorter than the 50-millisecond settle time the test broker uses, so the race is reproduced every time rather than by chance.

## Timing

The suite took about 37 seconds on 2026-09-15. The `slow` ping mode waits 0.3 seconds against a ping read timeout of 0.2 seconds, so each ping raises `ReadTimeout`; the other modes answer at once.
