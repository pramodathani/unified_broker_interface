# Notes on `stock_brokers/websockets/indmoney.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/indmoney/instruments/websocket_quotes` (`IndmoneySession`, `QuotesSocket` and the helpers `number` and `whole`) and `bin/indmoney/orders/websocket_order_details` (`OrderUpdatesSocket`). The offline recording in `test_runs/websocket_feeds/` reproduces every tick and order write.

## Why the session builds the handshake headers

Both old sockets built the same headers in their own `_connect`: the access token as `Authorization`, and the client id as `x-api-key` only when the settings hold one. `IndmoneySession.handshake_headers` builds them once for both, and returns the token too, so the quote socket still remembers which token it presented when it has to decide whether another process has already replaced it. The recordings `indmoney.quotes.without_client_id` and `indmoney.orders.without_client_id` pin the header being left out.

## Why the order socket picks the `data` object

An INDstocks order arrives either as `{"type": "order", "data": {...}}` or with the order's fields beside `type`. Choosing between the two is a question of how INDstocks frames its messages, so the socket makes it and hands over the order itself; the script only normalizes. An order the normalizer cannot read is still skipped without a log line, as before.

## Why the order socket logs in again without checking the token

As with Dhan, Shoonya and Flattrade, the old order socket logged in again whenever the handshake was refused, without checking whether another process had already replaced the token, and `IndmoneySession.log_in_again_without_checking` keeps that exactly. `indmoney.orders.token_replaced_elsewhere` pins it.
