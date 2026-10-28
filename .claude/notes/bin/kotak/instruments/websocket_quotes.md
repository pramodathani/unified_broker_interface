# bin/kotak/instruments/websocket_quotes

## Why the script moved back to sfeed on 2026-10-28

Kotak retired the HSM feed in October 2026; by 2026-10-27 `mlhsm.kotaksecurities.com` (121.240.153.195) refused TCP on port 443 and the newest Kotak tick was 24 days old. Kotak's notice "Kotak Neo Trade API market feed changes" deprecated the old feed from 2026-09-15 and pointed to the new market feed integration in `kotakneoapi` 3.0, whose `neo_api_client/websocket/feed` package talks to `wss://sfeed.kotaksecurities.com/apifeed` with the `native_batch` format. That is the address the script left on 2026-09-15, but not the same service: the server now calls itself `SFD_EBETA_710` rather than `SFD_CBETA_710`, it sends little-endian binary market pictures rather than one JSON snapshot, and it keeps sending. On 2026-10-28 during market hours, five instruments produced 59 market pictures in twelve seconds and two produced 23 in eight, against one snapshot per instrument on 2026-09-14. The socket subscribes with `subscribeDepth`, the level `kotakneoapi` calls depth, rather than `subscribeFullDepth`, the level that went quiet in September. The protocol and the measurements are in the note on `stock_brokers/websockets/kotak.py`.

The sections below describe the HSM feed and are kept as its history. Two of their conclusions no longer hold: MCX quantities are now in lots, as at Zerodha, not lots times Kotak's lot size, and the limit of 100 instruments per socket no longer comes from the channel's 200 subscriptions, since the feed takes one subscription per instrument; it was raised to 3,000 on 2026-10-28, as the section below explains.

## Why up to 3,000 instruments per socket

On 2026-10-28 `MAX_PER_SOCKET` went from 100 to 3,000, the most Kotak's SDK allows on one SFeed connection. A separate session first opened 3 to 45 connections of 3,000 in steps of 3, each subscribed in one message, with no refusal and no slowdown; the allocator then gave Kotak 45 × 3,000 in `unified.broker_quote_capacities`, and production ran 37 sockets for 109,608 instruments. Sockets first started together, because the probe opened 45 at once without trouble; the burst described next is why they now start two seconds apart.

Starting 37 sockets at once has two visible costs. Kotak sends a market picture for every instrument before it sends the subscription acknowledgement (message code 1109), so 28 of the 37 sockets reached `MAX_HELD_FRAMES` and decoded their held frames without the acknowledgement's names; the names from the scrip master cover them, and about 12,000 ticks of that burst reached the unified combiner keyed by token and were counted as ambiguous once each, after which the count stopped growing. The burst also put about 350,000 ticks into `kotak:quotes:stream` faster than the combiner reads, which delayed every broker's unified quotes by up to about 25 seconds for two minutes. In steady state the process used 40 to 68% of one core for about 4,200 ticks a second.

The same day `SOCKET_START_GAP_SECONDS` was set to 2. The combiner drained that burst's backlog in about two minutes while about 9,000 ticks a second kept arriving from Zerodha and Kotak, so it handles roughly 12,000 a second, about 3,000 above the live load. Two seconds apart, the sockets' first market pictures arrive at about 1,500 a second, inside that headroom, and 37 sockets take about 74 seconds to open, well before the 09:15 open after the 08:25 restart. This is an estimate from the one burst observed: a restart after the close showed no backlog because almost nothing was ticking, so the gap has not yet been seen working under market load.

## Why the script moved from sfeed to the HSM feed

Until 2026-09-15 the script connected to `wss://sfeed.kotaksecurities.com/apifeed` with a JSON authentication frame (`source` `NEOTRADEAPI`, message codes 1117 and 1120) and `subscribeFullDepth`. The server identified itself as `SFD_CBETA_710`. It acknowledged the subscription, sent one snapshot per instrument and then nothing: the service had been connected since 2026-09-14 14:21 with no reconnect, and `kotak.ticks` held 80 rows for the whole of 2026-09-14, all at session boundaries (15:30, 16:30, 06:00, 07:30, 08:30), with TCS at Friday's 2200.80 and volume 0.

A probe on 2026-09-15 at 10:08 IST opened both feeds with the same session and the same three instruments for sixty seconds. `sfeed` sent one snapshot and nothing else. `wss://mlhsm.kotaksecurities.com`, the feed in Kotak's official SDK (`Kotak-Neo/Kotak-neo-api-v2`, `neo_api_client/HSWebSocketLib.py`, commit 8cee5bd of 2026-06-08), sent updates in every one of the sixty seconds with TCS at 2292.80 and volume 1,883,508.

## Where the protocol comes from

The binary requests and the decoding follow `HSWebSocketLib.py`: `prepareConnectionRequest2` for the connection, `prepareSubsUnSubsRequest` for subscriptions, `get_acknowledgement_req` for acknowledgements and `HSWrapper.parseData` for data frames. The field indexes follow its `SCRIP_MAPPING` and `DEPTH_MAPPING`. The offline check compared the script's three requests with the SDK's byte for byte. Fields 0 and 1 (`ftm0`, `dtm1`) are not times despite their names; they read as small counters and are not used.

## Why acknowledgements are implemented

The connection reply on 2026-09-15 asked for an acknowledgement every five data frames. The SDK sends one after that many frames with the last message number, and a decoder that ignores the count misreads the four-byte message number as the packet count. It was not tested what the server does when acknowledgements stop, so the script simply sends them.

## Why each instrument has two topics and ticks are written per instrument

A scrip topic (`sf|`) carries prices and quantities; the order book comes only from a depth topic (`dp|`). The tick contract wants both in one dictionary, so `InstrumentQuote` holds the latest of each. Updates carry only changed fields, with -2147483648 for unchanged, so `FeedTopic` keeps every field's latest value and a whole tick is rebuilt on every change. Within one data frame an instrument whose scrip and depth topics both changed is written once, with both applied. A tick is not written until the scrip snapshot has arrived, because a depth-only tick would have no last price and the unified layer drops such ticks anyway.

## Why at most 100 instruments per socket

`NeoWebSocket.py` allows 200 tokens per channel and 3000 subscriptions per connection, and one subscription request takes at most 100 topics (`MAX_SCRIPS`). With two topics per instrument on channel 1, 100 instruments fill the channel. Spreading instruments over several channels on one connection would allow more, but it was not tried live, so extra instruments go on extra sockets instead.

## Why websocket pings are kept

The SDK runs with `ping_interval=0` and leaves its `hb` heartbeat thread commented out. Standard websocket pings every 30 seconds were kept from the previous script so a dead connection is noticed during quiet hours; the live check ran for sixty seconds with pings enabled and the server answered them without closing.

## What the measurements showed

A live check at 10:18 IST on 2026-09-15 ran `QuotesSocket` for sixty seconds against the eight subscribed instruments with an in-memory stand-in for Redis and compared the last tick with Zerodha's.

| Instrument | Kotak lot | Kotak volume | Zerodha volume | Kotak open interest | Zerodha open interest |
| --- | --- | --- | --- | --- | --- |
| GOLD05OCT26FUT | 1 | 562 | 562 | 9474 | 9474 |
| CRUDEOIL21SEP26FUT | 100 | 276900 | 2769 | 1598900 | 15989 |
| NATURALGAS25SEP26FUT | 1250 | 4943750 | 3955 | 49037500 | 39230 |

Last price, average price, close, last trade time and exchange timestamp matched Zerodha's on TCS, HDFCBANK and all three MCX contracts, the times to the second. The median gap between receipt and the exchange timestamp was 0.8 seconds on NSE and 1.2 to 1.7 seconds on MCX. This is why both tick normalizers now treat every MCX quantity as Kotak lots and trust both times.

## What is not handled

Index topics (`if|`) are not subscribed. Kotak names indices by name rather than a numeric `pSymbol`, which `_resolve_tokens` rejects, and the index topic's fields were not measured live.

## Where the socket went

On 2026-09-25 the socket this note describes moved out of the script into `KotakQuotesSocket` in `stock_brokers/websockets/kotak.py`, which also has a note of its own. The script now writes to Redis what the socket hands it. Where this note names the old class or function, the same code now lives there, and the offline recording in `test_runs/websocket_feeds/` shows the move changed nothing the script writes to Redis.
