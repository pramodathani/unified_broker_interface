# Notes on `stock_brokers/websockets/zerodha.py`

## Where this came from

The two classes were moved on 2026-09-25 out of `bin/zerodha/instruments/websocket_quotes` (`ZerodhaSession`, `QuotesSocket` and the packet helpers `unpack`, `split_packets`, `price_divisor` and `apply_change`) and `bin/zerodha/orders/websocket_order_details` (`OrderUpdatesSocket`). The decoding is the same arithmetic as before, down to the key order of the tick dictionary, and the index branch still builds `ohlc` as high, low, open, close rather than open, high, low, close, because the JSON written to Redis keeps the order the keys were inserted in. The offline recording in `test_runs/websocket_feeds/` was taken against the old scripts and reproduces every tick byte for byte.

The packet helpers became methods of `ZerodhaQuotesSocket`, following the rule that behaviour lives on the class that uses it.

## Why the order socket now uses `ZerodhaSession`

The old order socket built its own `ZerodhaAPI` and logged in again inline: read the current token, and if it was still the one that failed, log a warning and construct `ZerodhaAPI` again. That is exactly what `ZerodhaSession.log_in_again` does, with the same warning text, so the order socket now takes a session like the quote sockets do. The lock inside the session is never contended by a single socket, so the behaviour is unchanged, and the order socket still logs in when it is built, because the session logs in when it is built, which `main()` relies on to exit 1 when the first login fails.

## Why the order socket hands over Kite's orders rather than normalized ones

Normalizing an order uses the shared vocabulary tables, and the project keeps one copy of those tables in each script that normalizes orders, beside the poller that uses the same function. Moving `order_from_kite` into this module would have split that pair. The socket therefore picks the `order` messages out of the feed and hands their `data` over as Kite sent it, and the script normalizes it.

One consequence is visible in the log. The old socket decided that an `order` message without an order id was not an order at the moment it normalized it, and logged "Ignoring a message of type 'order'" in the middle of the message's other lines. The script now finds that out after the socket has handed the message over, so it logs "Ignoring an order update without an order id", with the order's data, after the socket's own lines for the same message. Nothing written to Redis changed.
