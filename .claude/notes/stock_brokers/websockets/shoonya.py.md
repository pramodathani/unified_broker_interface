# Notes on `stock_brokers/websockets/shoonya.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/shoonya/instruments/websocket_quotes` (`ShoonyaSession`, `QuotesSocket` and the helpers `number`, `trade_time` and `build_tick`) and `bin/shoonya/orders/websocket_order_details` (`OrderUpdatesSocket`). The decoding and the merging of Noren's incremental updates are unchanged, and the offline recording in `test_runs/websocket_feeds/` reproduces every tick.

## Why the quote socket has two callbacks

The old quote socket wrote to Redis at two points in one message: when an acknowledgement named an instrument it did not have a name for, it wrote that name to `shoonya:quotes:instruments` with a single `HSET`, and then it wrote the tick. `on_name` and `on_tick` are called at exactly those two points, so the name still reaches Redis before the tick that carries it. The names dictionary itself stays in the socket, because the socket reads it to key the tick; it is shared between the process's sockets as before.

The tick is handed over one at a time rather than as a list, because Noren sends one instrument per message and the old code wrote it with a single-field `HSET` rather than a mapping; the store keeps that command shape.

## Why this is not shared with Flattrade

Flattrade runs on the same Noren platform, and its feed code is close to this. The two are kept as separate files, as `historical/` and `ticks/` would have them only when the code is genuinely identical, because the user prefers self-contained per-broker code over a shared module, and because the two had already drifted: Flattrade confirms its session through UserDetails after every login, learns names in a different place, and writes ticks in batches.

## Why the order socket logs in again without checking the token

As with Dhan, the old order socket logged in again whenever the connect frame was refused, without checking whether another process had already replaced the token. `ShoonyaSession.log_in_again_without_checking` keeps that exactly, and `shoonya.orders.token_replaced_elsewhere` pins it. Shoonya's login drives a headless Chrome, so the extra login is slow, but changing it would be a change of behaviour and was not part of the move.

An `om` update whose normalizer returns None was skipped silently before, and still is: the socket passes on every `om` message that carries a `norenordno`, and the script skips what it cannot read without a log line.
