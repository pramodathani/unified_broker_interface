# Notes on `stock_brokers/websockets/flattrade.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/flattrade/instruments/websocket_quotes` (`FlattradeSession`, `QuotesSocket` and the helpers `number`, `trade_time` and `build_tick`) and `bin/flattrade/orders/websocket_order_details` (`OrderUpdatesSocket`). The offline recording in `test_runs/websocket_feeds/` reproduces every tick, name and order write.

## Why the order socket was moved although it is not run

Flattrade allows one websocket per session, so `flattrade.target` leaves the order updates unit out and Flattrade's orders come from the poller alone. The script is still kept working for the day that limit changes, so it was moved and recorded like every other broker's.

## Why the session is confirmed after every login

Noren answers a dead session with a refusal inside an HTTP 200, so `FlattradeAPI`'s constructor returning is no proof that the login worked. Both old scripts called `UserDetails` after every login and raised when it did not say `Ok`, and `FlattradeSession._confirm` does the same for both sockets now. A refused confirmation after logging in again ends the socket, which `flattrade.quotes.confirmation_refused_after_logging_in_again` pins.

## Why the names callback takes a dictionary

The old quote socket collected the names a frame taught it into a dictionary and wrote it with one `HSET` mapping before the frame's ticks, and it replaced a name whenever Noren's differed from the one held, not only when there was none. `on_names` receives that same dictionary at that same point. Shoonya's socket, which learns names only when it has none and writes them one field at a time, has a different callback for that reason.

## Why the order script builds its store before its session

The old order socket registered its merge script before it logged in. The script now creates `FlattradeOrderUpdatesStore`, which registers the merge script, before `FlattradeSession`, which logs in, so the order of the two is unchanged. The other brokers logged in first and their scripts build the session first.

## What the order store keeps from the old socket

The old socket merged every `om` update that carried a `norenordno`, keyed by that number, with `order` set to whatever `order_from_noren` returned, even None, and took `observed_at` from `time.time()` rather than from the receive time. The store does exactly that, and the socket still logs other message types at debug level. As with Dhan and Shoonya, the order socket logs in again without checking whether another process already replaced the token, through `FlattradeSession.log_in_again_without_checking`.
