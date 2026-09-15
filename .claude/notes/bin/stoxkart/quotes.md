# Notes on `bin/stoxkart/quotes`

## Why the script polls REST instead of streaming

Stoxkart's developer documentation describes a binary quote websocket at `ws://inmob.stoxkart.com:7763/?api_key=...&request_token=...`, with C# struct layouts for the requests and packets, and its .NET SDK uses the same address. On 2026-09-15, during market hours, the checks gave these results:

| What was tried | Result |
| --- | --- |
| TCP connection to `inmob.stoxkart.com` on ports 7763, 9443, 9444 and 9964 | Refused or timed out |
| TCP connection to the same host on port 443 | Open |
| Websocket handshake on `wss://inmob.stoxkart.com/` with the documented query | HTTP 503 `Service Temporarily Unavailable` from `awselb/2.0` |

The host resolves to a load balancer named `stx-pre-trade-alb`, which answers but has nothing behind it. Stoxkart's own web trading app at `webtrade.stoxkart.com` uses a different broadcast host and protocol, configured through Firebase remote config for the web platform. Reaching that would mean impersonating the web app rather than using the API access Stoxkart grants, so it was not pursued.

`POST https://openapi.stoxkart.com/quotes` works. It answers a full quote with five levels of depth for up to 50 instruments of one exchange in about 110 ms, and fifteen back-to-back requests were all answered. The script polls it once a second. Stoxkart documents a limit of 10 quote requests a second, and the script defaults to 8.

## What was checked against Zerodha

A Stoxkart quote and Zerodha's live tick for the same instruments were read in the same second:

| Field | Stoxkart | Zerodha |
| --- | --- | --- |
| CRUDEOIL SEP volume, open interest | 6385, 15677 | 6385, 15677 |
| CRUDEOIL SEP last trade time | 1473925604, plus 315532800 is 1789458404 | 1789458404 |
| TCS close | 2200.80 | 2200.80 |
| HDFCBANK close, volume | 708.25, 39518219 | 708.25, 39518219 |
| CRUDEOIL SEP `buy_quantity`, `sell_quantity` | 2, 5 | 689, 655 |

So `last_trade_time` counts seconds from 1980-01-01 UTC, `close` is the previous close during the session, and MCX quantities are lots. Stoxkart's `buy_quantity` and `sell_quantity` equal the best bid and ask sizes in its own depth, not the totals its documentation describes, so the tick stores null for both rather than a number that means something different at every other broker.

## Why unchanged quotes are not written

A poll returns the same quote for an instrument that has not traded. Writing it again would add a stream entry and a table row per instrument per second that says nothing new. The script compares each row with the previous one for the same instrument and writes only on a change. The fingerprint is the whole row, so a change in depth alone also counts.

## Why the tick count is logged once a minute

The first version reported each cycle through `PollReporter`, which repeats a message only when it changes. The count of changed ticks differs almost every cycle, so the filter let every line through, about 86,000 lines a day. The count is now summed and logged once a minute.

## How instruments are named

A future or option is named by its `symbol_description` when that begins with its `symbol`, such as `NIFTY26SEPFUT`. Stoxkart's MCX and some NCDEX descriptions are only the commodity's name, such as `LIGHT SWEET CRUDE OIL` for every CRUDEOIL expiry, which would give every expiry the same `id`. For those the name is built from the symbol, the expiry as `DDMONYY`, and for an option the strike in rupees and the option type, such as `CRUDEOIL21SEP26FUT`. The strike column of Stoxkart's master is in paise, so it is divided by 100.

## The subscription set

`stoxkart:quotes:subscriptions` was seeded on 2026-09-15 with the same fifteen instruments `zerodha:quotes:subscriptions` held: TCS, HDFCBANK, INFY, RELIANCE and ICICIBANK on NSE, and GOLD OCT, SILVERM NOV, SILVER DEC, CRUDEOIL SEP, CRUDEOILM SEP, NATURALGAS SEP, NATGASMINI SEP, GOLDM OCT, COPPER SEP and ZINC SEP on MCX. Using the same instruments lets the unified layer compare the brokers. The MCX members are dated contracts, so they have to be rolled when those contracts expire, as the other brokers' sets do.
