# bin/kotak/quotes

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
