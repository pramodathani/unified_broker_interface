# Notes on `stock_brokers/websockets/kotak.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/kotak/instruments/websocket_quotes` (`TruncatedFrameError`, `FrameReader`, `FeedRequests`, `FeedTopic`, `InstrumentQuote`, `KotakSession` and `QuotesSocket`) and `bin/kotak/orders/websocket_order_details` (`realtime_url` and `OrderUpdatesSocket`). The frame classes were already classes with Google docstrings; they took a `Kotak` prefix in the shared package, and `FeedRequests` lost its two static methods in favour of ordinary ones. The offline recording in `test_runs/websocket_feeds/` reproduces every frame sent, tick, name and order and position write.

## Why the quotes socket has two callbacks, and the order in which they fire

A snapshot that names an instrument without a name wrote that name to `kotak:quotes:instruments` in the middle of reading the frame, and the frame's ticks were written after the whole frame was read, in a `finally` block, so a frame cut short still wrote what it had read before its warning was logged. `on_name` is called at the same point in the packet loop, and `on_ticks` in the same `finally`, so the names, the ticks and the warning come in the old order; `kotak.quotes.every_frame_shape` pins all three.

## Why the quotes socket gives up later than the base class

As with Dhan and Groww, Kotak's old quotes loop gave up only after six more failed connects, not on the first refusal after logging in again, so `KotakQuotesSocket` overrides `_gives_up_after_logging_in_again`. `kotak.quotes.refused_again_logs_in_again` pins it.

## The order socket's session, host and refusal

The order socket reads its host from the stored login's `base_url` through `KotakSession.current_login`, and its connection frame from `KotakSession.credentials`, the same token and session id as before. It logs in again without checking whether another process already replaced the session, as it always did, through `KotakSession.log_in_again_without_checking`. A refusal still discards whatever else the same message carried: the socket returns before handing anything on, as `kotak.orders.refusal_drops_the_frame` pins.

## Where the order filtering went

The old socket used the normalizers to decide what counted as an order or a position: an order message whose `normalized_order` was None, or a position whose `position_key` was None, was logged as "Ignoring a message of type ..." among the message's other lines. The socket now hands over every order and position message's `data`, and the script's store skips and logs the ones its normalizers cannot read, after the socket's own lines for the message, as "Ignoring an order update without an order number" or "Ignoring a position update that names no segment, instrument or product". Nothing written to Redis changed.
