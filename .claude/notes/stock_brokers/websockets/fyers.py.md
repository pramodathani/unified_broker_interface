# Notes on `stock_brokers/websockets/fyers.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/fyers/instruments/websocket_quotes` (`FyersRefusal`, `refusal_code`, `is_block`, `is_throttle`, `is_authentication_error`, `token_claims`, `FyersSession`, `QuotesSocket` and the HSM helpers `auth_frame`, `auth_response`, `full_mode_frame`, `subscribe_frame`, `acknowledge_frame`, `topic_name`, `price_divisor`, `fields_for` and `build_tick`) and `bin/fyers/orders/websocket_order_details` (`token_expired` and `OrderUpdatesSocket`). The field tables, the segment table and all 175 index topic names were copied by program and compared with the originals, and the offline recording in `test_runs/websocket_feeds/` reproduces every frame sent, symbol lookup, tick and order and position write.

## One session for both sockets

The two old sockets each confirmed a new login against the profile endpoint, with the same check but different exceptions: the quotes socket raised `FyersRefusal` ("the profile was refused: ..."), the order socket `RuntimeError` ("the Fyers profile was refused: ..."). `FyersSession` has one confirmation for both, raising `FyersRefusal`, so the only visible difference is that wording in the order script's "Could not log in to Fyers" line when a profile is refused. The order socket's expiry check uses the session's `token_claims`: a token that cannot be decoded has no `exp`, and is treated as expired, as the old `token_expired` did.

The order socket logs in again without checking whether another process has already replaced the token, as it always did, through `FyersSession.log_in_again_without_checking`.

## Why the quotes socket keeps its own loop

A Cloudflare ban or a rate limit on the symbol lookup makes the socket wait out a pause and connect again, without counting a failure and without logging in, because every refused request extends a ban. That step sits in the middle of the loop, so `FyersQuotesSocket` overrides `run_forever` with the base loop plus that step, rather than the base class growing a hook for one broker.

## Why the order script builds its store before its session

The old order socket registered its merge script before it logged in; the script creates `FyersOrderUpdatesStore` first to keep that order, as Flattrade's does.

## What stays in the order socket

The socket decides which messages are orders and positions, using the same "has a value other than a blank or `NA`" test the old code borrowed from the normalizer's `text`, logs errors, the subscription answer and anything else, and closes the connection after handing on a message whose error carried a session code, so that message's orders are still written first, as before.
