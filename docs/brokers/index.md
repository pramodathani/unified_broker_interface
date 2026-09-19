# Brokers

Ten brokers, grouped by the platform they actually run on. Several are the same software behind a
different brand, which is why their scripts and modules come in families rather than being ten unrelated
implementations.

## Platform families

=== "Native protocols"

    **Zerodha** (Kite), **Dhan**, **Fyers**, **Groww**, **IND Money**, **Kotak** each speak their
    own protocol and get their own module in every subsystem.

    Groww is the odd one here: its feed is NATS over a websocket with protocol buffer payloads rather
    than a plain websocket. `bin/groww/quotes` generates an ed25519 key pair, exchanges its public key for
    a short lived socket JWT, signs the server's nonce in its `CONNECT`, and builds the protobuf message
    classes at runtime from a serialized file descriptor it carries itself.

=== "Noren"

    **Flattrade** and **Shoonya** are both deployments of the Noren platform. Each broker's scripts
    carry their own copy of the Noren protocol, and `stock_brokers/instruments/historical/noren.py` and
    `stock_brokers/instruments/ticks/noren.py` hold what their candle and tick modules share, so those
    brokers' own modules are a handful of lines.

    The Noren feed is incremental: a subscription acknowledgement carries every field and each
    update after it carries only what changed, so the quote script keeps per-instrument state and
    merges updates into it. A tick cannot be read from a single message.

    It connects with a frame of `t` of `a` carrying the session token as `accesstoken`,
    acknowledged with `ak`. Naming the same token `susertoken` in a `c` frame is parsed and
    refused with `NOT_OK`, which looks exactly like an expired session and is not one.

=== "Symphony XTS"

    **Wisdom Capital** runs Symphony's XTS, which differs from every other feed in four ways: the
    market data API has its own credentials and session, subscription happens over REST rather
    than on the socket, the transport is socket.io rather than a plain websocket, and orders and
    positions arrive in the same frame.

    `bin/wisdom_capital/quotes` carries its own Engine.IO and socket.io transport, and shares the market
    data token with `bin/wisdom_capital/historical_prices` through the Redis key
    `wisdom_capital:session:marketdata`.

=== "Website feeds"

    **Stoxkart** streams through the two websockets its own trading website uses, found by watching
    `webtrade.stoxkart.com` in Chrome DevTools on 2026-09-15. Its documented binary quote websocket at
    `ws://inmob.stoxkart.com:7763` refused connections that day, so `bin/stoxkart/quotes` streams the
    website's broadcast feed at `wss://broadcasting-v2.stoxkart.com/`, which needs no login and uses
    request codes 12 and 23 rather than the documented 71 to 76. Stoxkart documents only a Postback URL for
    order status, so `bin/stoxkart/order_updates` authenticates the API session at
    `https://openapi-v2.stoxkart.com/websocket/authenticate` and opens the website's order socket, which
    allows one connection per client. Neither feed is documented for API users, so Stoxkart may change
    them without notice.

## Per-broker notes

| Broker | Login | Worth knowing |
| --- | --- | --- |
| Zerodha | Selenium + TOTP | Tries an authenticated call first and only logs in when it fails, so most constructions are cheap; every login invalidates the token before it |
| Dhan | REST + TOTP | - |
| Flattrade | REST + TOTP | Permits one websocket per session, so `flattrade@order_updates` is not run and `flattrade@quotes` holds the connection |
| Shoonya | Selenium + TOTP | Its Noren user id is the account's UCC code, held in the `ucc_code` setting |
| Fyers | REST + TOTP | Streams positions as well as orders; refuses more than a handful of requests a second per app |
| Groww | REST + TOTP | NATS transport with protocol buffer payloads; streams derivatives positions |
| Kotak | REST + TOTP | Streams positions; its instrument master URL is stamped with today's date; its feed is the binary HSM protocol of Kotak's own SDK, which wants data frames acknowledged and sends MCX quantities in Kotak's lots |
| IND Money | REST + TOTP | - |
| Wisdom Capital | REST | XTS; separate market data credentials, REST subscription, socket.io transport, and `apiType=INTERACTIVE` required in the order socket's query; a stored-token check refused for rate (HTTP 429 or an `e-apirl` code) still counts as a working session, so it does not trigger a login |
| Stoxkart | REST + TOTP | Its version 2 login needs a publisher key pair in `publisher_api_key` and `publisher_api_secret` beside the app's own key, and that pair must stay in the settings document when the API key is changed; quotes and order updates stream from its trading website's websockets, and the order socket allows one connection per client; orders and cancellations must carry the Algo-ID `99999` in an `X-Algo-Id` header, because the body's `algo_id` alone is refused with `invalid algo_id` |

See the [coverage matrix](coverage.md) for what each broker supports subsystem by subsystem,
and [Pitfalls](../contributing/pitfalls.md#feeds-one-refusal-per-broker) for the way each of
these refuses a connection when it is got wrong.

## Running several connections per broker

A broker with more instruments than one connection can carry is split across several connections by its
own `quotes` script: `--per-socket` sets how many instruments one connection carries, and each connection
runs on its own thread, writing to the same `<broker>:quotes:live` and `<broker>:quotes:stream`.

```bash
bin/dhan/quotes --per-socket 2000
```

Zerodha splits the other way round. `bin/zerodha/quotes` takes every instrument in today's
`zerodha:instruments:master` and divides it into `--sockets` equal parts, 24 by default, one websocket each:

```bash
bin/zerodha/quotes --sockets 24
```

That is far past what Kite documents - three connections per api key, one of which `bin/zerodha/order_updates`
holds, and 3,000 instruments per connection - and the script no longer refuses to start when it is. See
[Known issues](../contributing/known-issues.md#broker-limits).
