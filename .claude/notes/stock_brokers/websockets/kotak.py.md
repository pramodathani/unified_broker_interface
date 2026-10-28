# Notes on `stock_brokers/websockets/kotak.py`

## Where this came from

The HSM classes listed here were replaced on 2026-10-28; see the next section. The classes were moved on 2026-09-25 out of `bin/kotak/instruments/websocket_quotes` (`TruncatedFrameError`, `FrameReader`, `FeedRequests`, `FeedTopic`, `InstrumentQuote`, `KotakSession` and `QuotesSocket`) and `bin/kotak/orders/websocket_order_details` (`realtime_url` and `OrderUpdatesSocket`). The frame classes were already classes with Google docstrings; they took a `Kotak` prefix in the shared package, and `FeedRequests` lost its two static methods in favour of ordinary ones. The offline recording in `test_runs/websocket_feeds/` reproduces every frame sent, tick, name and order and position write.

## Why the quotes socket moved to the SFeed feed

Kotak retired the HSM feed at `wss://mlhsm.kotaksecurities.com` over the weekend of 2026-10-02 to 2026-10-04, after announcing that the old market feed would be deprecated on 2026-09-15; by 2026-10-27 its address refused TCP on port 443 and Kotak's last tick in `kotak:quotes:live` was 24 days old. The replacement is the feed Kotak's SDK `kotakneoapi` 3.0 calls SFeed, and the socket follows that SDK's `neo_api_client/websocket/feed` package as of 3.0.9 (released 2026-10-15): the same authentication message, `user` the UCC and `auth` the session id, and the same packet layouts. The SDK prefers an address from Kotak's dynamic configuration service, then the login's `feedUrl`, then `wss://sfeed.kotaksecurities.com/apifeed`; the socket skips the configuration service, because the default address served the account's session on 2026-10-28, and uses `feedUrl` when the login stored one.

What was measured live on 2026-10-28, with the session `kotak-login` made at midnight:

- Kotak answered the authentication with message code 1119 and then 1117, each carrying the exchanges and dividers; the socket subscribes on the first and ignores the second.
- One `subscribeDepth` message for the 100 instruments in `kotak:quotes:subscriptions` (24 `nse_cm`, 18 `bse_cm`, 58 `cde_fo`) was acknowledged with `SUBSCRIBED` and 100 trading symbols, and every one of the 100 sent a market picture within 20 seconds.
- With a valid UCC and a made-up session id, Kotak still sent the 1119 and 1117 answers, a market picture and the acknowledgement, and only then message code 1120, "Auth failed ...", whose text repeats the session id it was given. So 1117 and 1119 are not an acceptance; the refusal comes after them, and the socket logs only the message code.
- The acknowledgement arrived after the first binary frame, which is why binary frames are held back until it has named the instruments. The holding stops if the acknowledgement never comes, after `HELD_FRAMES_PER_INSTRUMENT` frames per subscribed instrument, and never fewer than `MIN_HELD_FRAMES`. A fixed 1,000 suited sockets of 100 instruments but not 3,000: measured on 2026-10-28 at 21:40, Kotak sent 66 data frames before the acknowledgement for 100 instruments, 319 for 500, 601 for 1,000 and 1,797 for 3,000 (0.42 s), about 0.6 a instrument, so the limit is a little over three times what was seen. Under the fixed limit, 37 of 37 sockets of about 3,000 gave up waiting at 16:44 that day.
- Five instruments compared against Zerodha's ticks received within a second agreed on price, previous close, volume, open interest, total buy and sell quantity, best bid quantity, last trade time and exchange timestamp, MCX quantities in lots; see `stock_brokers/instruments/ticks/kotak.py`.

A market picture is the instrument's whole state, unlike the HSM feed's updates, so the socket keeps no per-topic state. Several pictures for one instrument often arrive in one frame, and only the last is handed on, as the HSM socket handed on one tick per changed instrument per frame. Untraded instruments send pictures with a last price of 0; the tick keeps 0, `change` is None, and the times are None, as `kotak.quotes.every_frame_shape` pins.

## Why the quotes socket gives up later than the base class

As with Dhan and Groww, Kotak's old quotes loop gave up only after six more failed connects, not on the first refusal after logging in again, so `KotakQuotesSocket` overrides `_gives_up_after_logging_in_again`. `kotak.quotes.refused_again_logs_in_again` pins it.

## The order socket's session, host and refusal

The order socket reads its host from the stored login's `base_url` through `KotakSession.current_login`, and its connection frame from `KotakSession.credentials`, the same token and session id as before. It logs in again without checking whether another process already replaced the session, as it always did, through `KotakSession.log_in_again_without_checking`. A refusal still discards whatever else the same message carried: the socket returns before handing anything on, as `kotak.orders.refusal_drops_the_frame` pins.

## Where the order filtering went

The old socket used the normalizers to decide what counted as an order or a position: an order message whose `normalized_order` was None, or a position whose `position_key` was None, was logged as "Ignoring a message of type ..." among the message's other lines. The socket now hands over every order and position message's `data`, and the script's store skips and logs the ones its normalizers cannot read, after the socket's own lines for the message, as "Ignoring an order update without an order number" or "Ignoring a position update that names no segment, instrument or product". Nothing written to Redis changed.

Kotak streams at most `INSTRUMENTS_PER_CONNECTION`, 3,000, instruments on one connection, counted across subscription messages, and still acknowledges every instrument as `SUBSCRIBED`. For each instrument past the limit it sends message code 1, `{"message_code": 1, "message": "Subscription limit reached"}`, so the socket warns once per connection, with how many of its instruments were refused, instead of once per refused instrument.

## Why a dropped order updates connection is a warning

The order updates socket logged about 26 dropped connections in each market session from 2026-10-26, and 44 between 18:00 and 23:00 on 2026-10-28, each as two `ERROR` lines: `Order updates error: Connection to remote host was lost.` from this socket, and websocket-client's own `Connection to remote host was lost. - goodbye`. Before 2026-10-26 the socket had not stayed connected long enough to show it: it was not running on 2026-10-20, and on 2026-10-23 and 2026-10-24 it could not log in while MongoDB refused connections.

Kotak's SDK `kotakneoapi` 3.0.9 connects to the same address, `wss://e43.kotaksecurities.com/realtime` for this account's data centre E43 (its dynamic config service gives `E43_sh_interactive_endpoint` as that address), sends only websocket pings every 20 seconds where this socket sends them every 30, and reconnects by itself after a drop, noting that the server pushes the state again on reconnect.

On 2026-10-28 from 23:05 to 23:45 three extra connections on the production session pinged every 30, 20 and 10 seconds. Each of them, and the production socket, dropped exactly three times, with lifetimes of 945, 321, 149 and 990 seconds at 30, 1001, 255, 180 and 970 at 20, and 987, 225, 247 and 937 at 10. The drops came in three waves, 23:20:51 to 23:21:47, 23:25:19 to 23:26:13 and 23:28:43 to 23:29:27, with every connection cut within about a minute of the others, so Kotak closes them on its side and no ping interval avoids it.

The socket therefore logs a `WebSocketConnectionClosedException` as a warning and lets the base class reconnect; the base class still logs an error when connecting fails, and any other error passed to `_on_error` is still an error. websocket-client's own `goodbye` line is left as it is, because it is logged for every broker and silencing it would hide other brokers' failures. The replay `kotak.orders.dropped_connection_is_a_warning` pins both cases.
