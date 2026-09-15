# Notes on `bin/stoxkart/quotes`

## How the feed was found

Stoxkart's developer documentation describes a binary quote websocket at `ws://inmob.stoxkart.com:7763/?api_key=...&request_token=...`, and its .NET SDK uses the same address. On 2026-09-15, during market hours, that address did not work:

| What was tried | Result |
| --- | --- |
| TCP to `inmob.stoxkart.com` on ports 7763, 9443, 9444 and 9964 | Refused or timed out |
| Websocket handshake on `wss://inmob.stoxkart.com/` | HTTP 503 from `awselb/2.0`, a load balancer named `stx-pre-trade-alb` with nothing behind it |
| `superapi.stoxkart.com`, a name the user suggested | No DNS record |
| `superrapi.stoxkart.com`, linked from the documentation | The Superr marketing site; handshakes on `/`, `/ws`, `/websocket`, `/socket`, `/feed` and `/stream` timed out, and the feed ports were closed |

The first version of this script therefore polled `POST https://openapi.stoxkart.com/quotes` once a second. That version is in git history, in the commit that added Stoxkart's scripts, and is the fallback if the broadcast host changes.

The user then opened Stoxkart's trading website, `webtrade.stoxkart.com`, in a separate Chrome profile started with a remote debugging port, and logged in themselves. A small recorder attached through the Chrome DevTools Protocol logged every websocket the page and its web workers opened, keeping only addresses, header names and frame sizes. The website opened `wss://broadcasting-v2.stoxkart.com/` for market data and `wss://openapi-v2.stoxkart.com/websocket/v2/connect` for order updates, both on port 443.

## Why no login is sent

The website's worker sends an 83-byte connection header whose 30-byte client field holds a device id and whose 50-byte token field is blank, and no token appears in the URL or the handshake headers. The script does the same, with `unified_broker_interface` as the client name. This is the one part of Stoxkart's integration that does not use the API app's credentials, because the feed asks for none. The user chose to build on it knowing it is undocumented for API users.

## The protocol

The request codes differ from the API documentation. The documentation lists 71 to 76 for subscriptions, while the website's code uses 10 for the connection header, 12 to subscribe trades, 23 to subscribe depth, 24 for indices, 66 for bulk subscriptions and 13, 25 and 28 to unsubscribe. The website reads these defaults from its bundle but can override them from Firebase remote config, which was not read, so a change there would show up as a feed that connects but sends nothing.

The packet layouts were read from the website's worker, `worker-DlOSFlhD.js`. Each packet starts with an 11-byte header: segment (byte), scrip id (uint32), a second id (uint32), packet length (byte) and packet code (byte). A frame holds several packets back to back, and each instrument's packets for a moment arrive together. The worker also handles packet codes 5 (index), 33 (circuit limits), 36 (52-week range), 37 (bulk last price) and 40 (call auction), which this script does not use.

The segment numbers were confirmed by subscribing and watching for trade packets: NSE 1 (KWIL), NFO 2 (NIFTY SEP future), BSE 4 (KWIL on BSE) and MCX 5 (CRUDEOIL SEP). MCX spot contracts answered on 6. An NSE currency future on 3, 13 and 14, a BSE currency future on several guesses and an NCDEX spread on several guesses sent no trade in twelve seconds, so those exchanges are refused rather than subscribed on a guess.

## What was checked against Zerodha

A streamed Stoxkart tick and Zerodha's tick were read from Redis within a second of each other at 14:10 IST:

| Instrument | Matched exactly | Differed |
| --- | --- | --- |
| TCS | last price 2275, last quantity, volume, OHLC, previous close 2200.8, last trade time, exchange time | total bid 161470 against 160771 and depth, from snapshots taken at slightly different moments |
| HDFCBANK | volume, average price, total bid 1101904 and offered 4308564, OHLC, first depth level, last trade time | last price 717.15 against 717.0 and exchange time by one second, one tick apart |
| RELIANCE | every field compared, including total bid, first depth level and both times | nothing |
| CRUDEOIL SEP | last price 9942, volume 8997, open interest 15634, total bid 786 and offered 590, OHLC, previous close 9717, first depth level, last trade time | exchange time, which Stoxkart sends as 0 on MCX |

So MCX quantities are lots as at Zerodha, `last_trade_time` counts seconds from 1980-01-01 UTC, and the trade packet's last update time counts India wall-clock seconds from 1980, which is why 19800 seconds are taken off it.

## Why the previous close comes from its own packet

The OHLC packet's close field held the previous close for NSE instruments (TCS 2200.8) but 0 for MCX ones, while the previous close packet held the previous close for both (CRUDEOIL 9717). The tick's `ohlc.close` is therefore always taken from the previous close packet.

## Why unchanged ticks are not written

Stoxkart sends an instrument's packets several times a second even when only the depth moves, and sometimes when nothing does. A tick identical to the previous one, apart from `received_at`, is skipped, so the stream and `stoxkart.ticks` hold changes rather than repeats.

## How instruments are named

A future or option is named by its `symbol_description` only when that description begins with the symbol, is longer than it, has no space and contains a digit, as `NIFTY26SEPFUT` does. The first rule, "begins with the symbol", passed `GOLD 995`, `COPPER`, `SILVER` and `ZINC` for four MCX contracts, which named every expiry of those commodities alike. Those contracts are now named from the symbol, the expiry as `DDMONYY`, and for an option the strike in rupees and the option type, such as `COPPER30SEP26FUT`. The 6,082 rows `stoxkart.ticks` had stored under the four wrong names by then were renamed by `instrument_token` rather than deleted.

## The subscription set

`stoxkart:quotes:subscriptions` was seeded on 2026-09-15 with the fifteen instruments `zerodha:quotes:subscriptions` held, so the unified layer can compare the brokers on the same instruments. The MCX members are dated contracts and have to be rolled when they expire, as the other brokers' sets do.
