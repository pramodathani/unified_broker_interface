# Notes on `stock_brokers/websockets/stoxkart.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/stoxkart/instruments/websocket_quotes` (`StoxkartBroadcastRequests`, `StoxkartInstrumentState`, `StoxkartPacketDecoder` and `StoxkartQuoteStream`) and `bin/stoxkart/orders/websocket_order_details` (`StoxkartSessionRefused` and `StoxkartOrderSocket`). They were already classes with Google docstrings, and moved nearly as they were. The offline recording in `test_runs/websocket_feeds/` reproduces every frame, tick, authentication request and order write without a single changed line, because neither stream uses the shared reconnect loop and its wording.

## Why neither stream subclasses `BrokerWebsocket`

Both read a synchronous websocket-client connection (`create_connection` and `recv_data`) in a loop of their own rather than handing callbacks to `WebSocketApp`. The quote stream pings with text and reconnects on silence or on Stoxkart's `reconnect` text, and needs no login. The order socket authenticates over REST for a RequestId before each connection, and waits five minutes after being evicted by another session. None of that fits the base class's connect, refuse and log-in-again loop, so these two are the package's one exception, as the plan for the move said they would be.

## What changed at the boundary

The two streams used to call `get_cache()` and `get_logger()` themselves, and the scripts imported `websocket`, `requests` and `StoxkartAPI` when they loaded. The streams now take a logger and a callback, import `websocket` and `requests` when they connect, and the order socket takes a `StoxkartSession`, which constructs `StoxkartAPI` and logs in again when the authentication is refused.

The order socket used to read `stoxkart:orders:orders` in the middle of handling a frame, to keep an `AMO` or `BO` variety the order book had already stored. That read belongs to the script, so the socket now hands over the frame's messages and the script's `StoxkartOrderUpdatesStore` normalizes them, reads the stored varieties and merges them, in the same order as before.
