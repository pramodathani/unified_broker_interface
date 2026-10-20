# Notes on `stock_brokers/websockets/groww.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/groww/instruments/websocket_quotes` (`STOCKS_DESCRIPTOR`, `stocks_response_class`, `crc16`, `NkeyPair`, `SocketRefused`, `GrowwSession` and `QuotesSocket`) and `bin/groww/orders/websocket_order_details` (`ORDERS_DESCRIPTOR`, `POSITIONS_DESCRIPTOR`, `message_classes`, `as_dict`, `crc16`, `NkeyPair`, `SocketRefused` and `OrderUpdatesSocket`). The offline recording in `test_runs/websocket_feeds/` reproduces every socket token request, NATS line sent, tick, and order and position write.

## Why the NATS reading is one class

Both old sockets carried the same `consume_nats`: buffer the stream, pull out whole `MSG` payloads, and act on `INFO`, `PING` and `-ERR` lines as they come. The two differed only in what each did with those lines. `GrowwNatsBuffer.feed` does the buffering once and hands back the lines in order, and each socket acts on them in that same order, so a `PONG` or a `CONNECT` is still sent at the point in the stream where the old code sent it, and messages are still processed after the frame's control lines.

## Why the session returns the socket token's payload

The quotes socket needs only the JWT, and the order socket needs the JWT and the subscription id, and the two old sockets raised different errors when the answer lacked what they needed. `GrowwSession.socket_token_payload` makes the request and raises for a refused or failed one; each socket checks the payload for what it needs and raises its own error, with the old wording.

## Why the quotes socket gives up later than the base class

As with Dhan and Kotak, Groww's old quotes loop gave up only after six more failed connects, not on the first refusal after logging in again, so `GrowwQuotesSocket` overrides `_gives_up_after_logging_in_again`. `groww.quotes.refused_again_logs_in_again` pins it.

## Where the order normalizing went

The old order socket decoded each protobuf message and normalized it in the same `try` block, so a message that failed either way was reported as "Could not decode a payload on <subject>". The socket still decodes, filters out orders without a `growwOrderId` and positions without `symbolData`, and reports decoding failures in the old words. Normalizing now happens in the script's store, which reports a failure there as "Could not normalize an order update" or "... a position update", since it no longer knows the subject. Neither normalizer raises for the messages Groww sends, so this has not been seen to happen.

## Why only the first INFO is answered

A NATS server may send `INFO` again on an open connection, for example when its cluster changes, and a client is meant to answer only the first. Both sockets used to answer every `INFO` with `CONNECT` and their whole set of `SUB` lines. From about 2026-10-09 Groww's server began sending a second `INFO` on many connections: on the 8th the order socket subscribed exactly once per connection (141 connections, 141 rounds), while on the 18th it made 4,423 subscribe rounds over 2,251 connections. Groww refuses the doubled subscriptions with `-ERR 'maximum subscriptions exceeded'` and then `-ERR 'Authorization Violation'`; the socket took that as a refused login, logged in again, gave up and exited, and systemd restarted it every few seconds, all day.

`_answer_info` now authenticates on a connection's first `INFO` and logs and ignores any later one. `_greeted` is set back to false in `_on_open`, which runs once per connection. The quotes socket had the same code and the same exposure, though with a larger subscription allowance it had not yet hit the limit. `groww.orders.second_info_is_ignored` and `groww.quotes.second_info_is_ignored` pin one `CONNECT` and one round of `SUB` lines when the server greets twice; both differ from the recording with the old code.

## Test notes

`GrowwNkeyPair` generates a fresh ed25519 key per connection, so the NKEY and the nonce signature change on every run. The recording patches `Ed25519PrivateKey.generate` to return a key built from fixed bytes, and masks the random `x-request-id` header of the socket token request.
