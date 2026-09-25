# Brokers

The project connects to ten Indian stock brokers. They all end up behind the same REST API, but they do not all offer the same things: some stream positions, some serve historical candles, and some cannot be quoted over REST. This page shows what each broker supports, built from the files that actually exist in the repository, and then gives each broker's login, websocket protocol and peculiarities in a tab of its own.

## Coverage matrix

The first table covers the scripts in `bin/<broker>/`, one column per script or group of scripts. A tick means the file exists for that broker.

| Broker | Session connect | User details | API orders | API trades | Websocket orders | Positions stream | Positions, holdings, funds | Store positions to DB | Daily feed | Websocket quotes | Price history |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Dhan | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-close: | :material-check: | :material-close: | :material-check: | :material-check: | :material-check: |
| Flattrade | :material-check: | :material-check: | :material-check: | :material-check: | :material-check:[^flattrade-ws] | :material-close: | :material-check: | :material-close: | :material-check: | :material-check: | :material-check: |
| Fyers | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: |
| Groww | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-close: |
| INDmoney | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-close: | :material-check: | :material-close: | :material-check: | :material-check: | :material-check: |
| Kotak | :material-check: | :material-close:[^kotak-profile] | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-close: |
| Shoonya | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-close: | :material-check: | :material-close: | :material-check: | :material-check: | :material-check: |
| Stoxkart | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-close: | :material-check: | :material-close: | :material-check: | :material-check: | :material-close: |
| Wisdom Capital | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: |
| Zerodha | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-close: | :material-check: | :material-close: | :material-check: | :material-check: | :material-check: |

The columns map onto files like this: session connect is `session/connect`, user details is `user/details`, the three order columns are `orders/api_order_details`, `orders/api_trade_details` and `orders/websocket_order_details`, and the portfolio columns are `portfolio/{positions,holdings,funds}` and `portfolio/store_positions_to_db`. The positions stream column means the broker's order websocket also carries positions, so its script writes `<broker>:positions_updates:stream`.

The second table covers the classes in the REST API's packages, which decide whether the API can fetch a quote from the broker and place orders there.

| Broker | REST quote source | Order placement class | Modify support | Fields a modify can change |
|---|:---:|:---:|:---:|---|
| Dhan | :material-check: | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type, validity |
| Flattrade | :material-check: | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type, validity |
| Fyers | :material-close:[^quote-held] | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type |
| Groww | :material-close:[^quote-held] | :material-check: | :material-check: | quantity, price, trigger price, order type |
| INDmoney | :material-check: | :material-check: | :material-check: | quantity, price |
| Kotak | :material-check: | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type, validity |
| Shoonya | :material-check: | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type, validity |
| Stoxkart | :material-close: | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type, validity |
| Wisdom Capital | :material-close: | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type, validity |
| Zerodha | :material-check: | :material-check: | :material-check: | quantity, disclosed quantity, price, trigger price, order type, validity |

A REST quote source is a registered class in `SOURCES` in `unified_broker_interface/utilities/broker_quotes/utilities/service.py`, used when no fresh live quote is cached. An order placement class is a subclass of [`BrokerOrders`][unified_broker_interface.utilities.broker_orders.base.BrokerOrders] in `unified_broker_interface/utilities/broker_orders/`. The modify fields are each class's `MODIFIABLE_FIELDS`; a field outside that list is refused, and a broker with an empty list would be answered with HTTP 501.

[^flattrade-ws]: The script exists, but `services/flattrade/flattrade.target` leaves it out, because Flattrade permits one websocket per session and the quote feed holds it.
[^kotak-profile]: Kotak has no profile endpoint. `KotakAPI` writes the profile to `kotak:user:details` itself at every login, from the login response.
[^quote-held]: A module exists (`fyers.py`, `groww.py`), but it is not registered. The Fyers module's field mapping is unverified because every probe met Fyers' request limit, and the Groww account is not entitled to live data and is refused with HTTP 403.

## Features per broker

The chart below counts the ticks in both tables for each broker, out of the 14 feature columns in the two tables: the eleven script columns, plus REST quote source, order placement class and modify support.

```vegalite
{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "description": "Number of the 14 features in the coverage matrix that each broker supports.",
  "width": "container",
  "height": 280,
  "data": {"values": [
    {"broker": "Fyers", "features": 13},
    {"broker": "Wisdom Capital", "features": 13},
    {"broker": "Dhan", "features": 12},
    {"broker": "Flattrade", "features": 12},
    {"broker": "Groww", "features": 12},
    {"broker": "INDmoney", "features": 12},
    {"broker": "Kotak", "features": 12},
    {"broker": "Shoonya", "features": 12},
    {"broker": "Zerodha", "features": 12},
    {"broker": "Stoxkart", "features": 10}
  ]},
  "layer": [
    {
      "mark": {"type": "bar", "color": "#2a78d6", "cornerRadiusEnd": 4, "height": {"band": 0.6}},
      "encoding": {
        "y": {"field": "broker", "type": "nominal", "sort": "-x", "title": null},
        "x": {"field": "features", "type": "quantitative", "title": "Features supported (of 14)", "scale": {"domain": [0, 14]}},
        "tooltip": [
          {"field": "broker", "title": "Broker"},
          {"field": "features", "title": "Features"}
        ]
      }
    },
    {
      "mark": {"type": "text", "align": "left", "dx": 4},
      "encoding": {
        "y": {"field": "broker", "type": "nominal", "sort": "-x"},
        "x": {"field": "features", "type": "quantitative"},
        "text": {"field": "features", "type": "quantitative"}
      }
    }
  ]
}
```

A higher count does not mean a broker is used more. The unified quote combiner, for example, prefers Zerodha for every instrument Zerodha streams, although Zerodha has fewer ticks here than Fyers.

## What every broker has in common

Before the differences, it helps to know what is the same for all ten. Every broker class in `stock_brokers/api/` first tries an authenticated call with the stored token and only logs in when that call fails. A successful login writes the token to MongoDB `last_login` first and to the Redis hash `last_login` second, so a token obtained by any process is used by all of them. Every websocket reads its credentials afresh on each connect, and every quote socket logs in again one socket at a time, and only when no other socket or process has already replaced the token that failed. [Sessions and logins](../architecture/sessions.md) explains the mechanism.

## Each broker

Each tab below describes one broker from its code: how it logs in (from `stock_brokers/api/<broker>.py`), how its websockets work (from the docstring of `stock_brokers/websockets/<broker>.py`), what is unusual about it, and which files belong to it.

=== "Dhan"

    **Login.** `DhanAPI` probes `GET https://api.dhan.co/v2/profile`. When that fails, it posts the client id, PIN and the current TOTP to `https://auth.dhan.co/app/generateAccessToken` and stores the access token it gets back. There is no browser step.

    **Websockets.** The quote feed is the DhanHQ v2 market feed at `wss://api-feed.dhan.co`, with the token and client id in the URL. Instruments are subscribed in full mode (request code 21), a hundred per message. Data arrives as little-endian binary packets, each with an eight-byte header, and the packet's response code says what it holds.

    | Code | Packet | Length |
    |---|---|---|
    | 2 | Ticker | 16 |
    | 4 | Quote | 50 |
    | 5 | Open interest | 12 |
    | 6 | Previous close | 16 |
    | 8 | Full, with five levels of depth | 162 |
    | 50 | Disconnect, with a reason code | 10 |

    Order updates come from `wss://api-order-update.dhan.co`, after a JSON login message with `MsgCode` 42. Dhan does not answer a successful login, so any binary frame on that socket is taken as a refused login.

    **Peculiarities.**

    - Previous close and open interest arrive in packets of their own, so they are remembered per instrument and folded into the ticks that follow.
    - Dhan's trade times are India wall-clock seconds presented as an epoch, so 19,800 seconds are taken off.
    - Disconnect codes 807, 808 and 809 mean a refused login; other codes are only logged.
    - Dhan allows 5 quote connections per user, with at most 5,000 instruments on each.

    **Files.** `stock_brokers/api/dhan.py`, `stock_brokers/websockets/dhan.py`, `stock_brokers/instruments/dhan.py`, `stock_brokers/instruments/mapping/dhan.py` with `mapping/utilities/rules/dhan.yaml`, `stock_brokers/instruments/historical/dhan.py`, `stock_brokers/instruments/ticks/dhan.py`, `unified_broker_interface/utilities/broker_quotes/dhan.py`, `unified_broker_interface/utilities/broker_orders/dhan.py`, `bin/dhan/`, `services/dhan/`.

=== "Flattrade"

    **Login.** Flattrade runs on the Noren platform. `FlattradeAPI` checks the session with `UserDetails` and, because Noren refuses a dead session inside an HTTP 200, also checks that the body says `stat: ok`. To log in, it opens a session at `https://auth.flattrade.in/auth/session`, posts the username, the SHA-256 of the password and the current TOTP to `https://auth.flattrade.in/ftauth`, reads a request code from the redirect URL, and exchanges it at `https://authapi.flattrade.in/trade/apitoken` with the SHA-256 of the API key, the code and the API secret. There is no browser step.

    **Websockets.** Both sockets connect to `wss://piconnect.flattrade.in/PiConnectWSTp/` and speak Noren's JSON protocol. On open, a socket sends an `a` frame with the user id and `accesstoken`, and subscribes only after the `ak` acknowledgement says `OK`. Quotes are subscribed with one `{"t": "d", "k": "NSE|2885#MCX|565899"}` frame for depth and touchline together. The feed is incremental: an acknowledgement (`tk`, `dk`) carries every field and each update after it (`tf`, `df`) only what changed, so the last state is kept and merged. Order updates arrive as `om` messages after an `o` subscription for the account.

    **Peculiarities.**

    - Flattrade permits only one websocket per session, so in production the order updates socket is not run and orders come from the poller alone.
    - Noren also accepts a `c` connect frame but answers it `NOT_OK` for a good token, which looks like an expired session and is not one.
    - Noren's heartbeat `{"t":"h"}` is sent every three seconds, because a plain websocket ping is not enough.
    - Flattrade shares `NorenCandles` with Shoonya for candles, `NorenOrders` for orders and `NorenQuoteSource` for REST quotes. Its candle downloader runs at 10 requests a second, ten times Shoonya's.
    - Flattrade's NSE daily bars are raw across some corporate actions and already adjusted across others, which the unified price history detects and corrects.

    **Files.** `stock_brokers/api/flattrade.py`, `stock_brokers/websockets/flattrade.py`, `stock_brokers/instruments/flattrade.py`, `stock_brokers/instruments/mapping/flattrade.py` with `rules/flattrade.yaml`, `stock_brokers/instruments/historical/flattrade.py` and `noren.py`, `stock_brokers/instruments/ticks/flattrade.py` and `noren.py`, `unified_broker_interface/utilities/broker_quotes/flattrade.py`, `unified_broker_interface/utilities/broker_orders/flattrade.py` and `noren.py`, `bin/flattrade/`, `services/flattrade/`.

=== "Fyers"

    **Login.** `FyersAPI` probes `GET https://api-t1.fyers.in/api/v3/profile`. Its login takes five requests, with no browser:

    1. Request a login OTP for the Fyers id (`vagator/v2/send_login_otp_v2`).
    2. Verify it with the current TOTP (`vagator/v2/verify_otp`), waiting past the 30-second boundary when it is three seconds or less away, because Fyers refuses a code verified too close to it.
    3. Verify the PIN (`vagator/v2/verify_pin_v2`).
    4. Ask for an OAuth auth code (`api/v3/token`).
    5. Exchange the auth code for the day's access token (`api/v3/validate-authcode`).

    **Websockets.** Quotes use the binary protocol Fyers' SDK calls HSM, at `wss://socket.fyers.in/hsm/v1-5/prod`. The feed is authenticated not with the access token but with the `hsm_key` claim inside it. Each connect first resolves symbols to fytokens through `POST https://api-t1.fyers.in/data/symbol-token`, then subscribes topic names such as `sf|nse_cm|3045`, 1,500 per frame. Order and position updates come from `wss://socket.fyers.in/trade/v3` after a `SUB_ORD` message for `orders` and `positions`.

    **Peculiarities.**

    - The access token is a JWT, and a token whose `exp` has passed is treated as refused without sending anything, because Fyers' edge bans addresses that keep sending refused requests.
    - A Cloudflare ban pauses the quote socket and the pollers for thirty minutes and a rate limit for five, rather than logging in again.
    - Fyers allows an app 200 requests a minute and 100,000 a day across every endpoint, so its pollers run slower than other brokers': orders every 5 seconds, trades every 15, funds every 30.
    - It is one of four brokers whose order websocket also carries positions.
    - Its REST quote module exists but is not in service, because its field mapping could not be verified.

    **Files.** `stock_brokers/api/fyers.py`, `stock_brokers/websockets/fyers.py`, `stock_brokers/instruments/fyers.py`, `stock_brokers/instruments/mapping/fyers.py` with `rules/fyers.yaml`, `stock_brokers/instruments/historical/fyers.py`, `stock_brokers/instruments/ticks/fyers.py`, `unified_broker_interface/utilities/broker_quotes/fyers.py` (not in service), `unified_broker_interface/utilities/broker_orders/fyers.py`, `bin/fyers/`, `services/fyers/`.

=== "Groww"

    **Login.** `GrowwAPI` probes `GET https://api.groww.in/v1/user/detail`. To log in, it posts the current TOTP to `https://api.groww.in/v1/token/api/access`, authorized with the account's stored TOTP token as a bearer token, and stores the access token it gets back.

    **Websockets.** Both sockets are NATS over a websocket at `wss://socket-api.groww.in`. Before connecting, a socket generates a fresh ed25519 key pair and exchanges its public key for a short-lived socket JWT and a subscription id, authorized with the access token. It then answers the server's `INFO` nonce with a signed `CONNECT`. Quotes subscribe a price subject and a depth subject per instrument, such as `/ld/eq/nse/price_detailed.2885` and `/ld/eq/nse/book.2885`, and payloads are protobuf messages decoded from Groww's own file descriptor. The order socket subscribes the account's order and derivatives position subjects.

    **Peculiarities.**

    - Prices arrive in paise and are divided into rupees; quantities arrive as doubles and are rounded.
    - Groww's feed has no subjects for commodities, so commodity tokens are skipped.
    - Groww sends no token with orders, positions or holdings, so the unified scripts look a Groww cash instrument up by symbol in `unified:instrument_symbols`.
    - Groww's lot sizes are the authority on MCX when the brokers disagree.
    - It is one of four brokers whose order websocket also carries positions.
    - It has no candle downloader, and its REST quote module is not in service because the account is refused live data with HTTP 403.

    **Files.** `stock_brokers/api/groww.py`, `stock_brokers/websockets/groww.py`, `stock_brokers/instruments/groww.py`, `stock_brokers/instruments/mapping/groww.py` with `rules/groww.yaml`, `stock_brokers/instruments/ticks/groww.py`, `unified_broker_interface/utilities/broker_quotes/groww.py` (not in service), `unified_broker_interface/utilities/broker_orders/groww.py`, `bin/groww/`, `services/groww/`.

=== "INDmoney"

    **Login.** INDmoney's API is INDstocks. `INDMoneyAPI` probes `GET https://api.indstocks.com/user/profile`. To log in, it posts the MPIN and the current TOTP to `https://api.indstocks.com/generate/token`, with the client id as `x-api-key`.

    **Websockets.** Quotes come from `wss://ws-prices.indstocks.com/api/v1/ws/prices` in `full` mode, the richest the feed serves. Every update is a JSON string whose content is itself JSON, so each line is decoded twice, and each update carries only what changed. Order updates come from `wss://ws-order-updates.indstocks.com/api/v1/ws/trades`. A dead token is refused at the handshake with HTTP 401, 403 or 513.

    **Peculiarities.**

    - Every quote socket carries instruments of one segment only, because an update names its instrument by a bare security id.
    - `close` is sent as the last price, not the previous close, and the best bid and offer are the only depth, without quantities.
    - Its instrument master is the only one that is not public: three CSV files behind an access token, which the ingester logs in for through `ensure_session` when no usable token is stored.
    - INDstocks names no trading symbol on orders, so the unified orders document leaves `id` null until the instrument supplies a symbol.
    - Its REST quote source refuses every BSE cash quote, because INDstocks answers a dual-listed stock's BSE code with the NSE quote, and it does not serve MCX.

    **Files.** `stock_brokers/api/indmoney.py`, `stock_brokers/websockets/indmoney.py`, `stock_brokers/instruments/indmoney.py`, `stock_brokers/instruments/mapping/indmoney.py` with `rules/indmoney.yaml`, `stock_brokers/instruments/historical/indmoney.py`, `stock_brokers/instruments/ticks/indmoney.py`, `unified_broker_interface/utilities/broker_quotes/indmoney.py`, `unified_broker_interface/utilities/broker_orders/indmoney.py`, `bin/indmoney/`, `services/indmoney/`.

=== "Kotak"

    **Login.** `KotakAPI` probes `GET {base_url}/quick/user/positions`. Its login takes two requests, with no browser: the mobile number, UCC and current TOTP go to `https://mis.kotaksecurities.com/login/1.0/tradeApiLogin`, and the MPIN goes to `tradeApiValidate` with the token and session id from the first answer. The second answer carries the token, the session id and a `baseUrl`, all of which are stored.

    **Websockets.** Quotes use Kotak's HSM feed at `wss://mlhsm.kotaksecurities.com`, where every frame begins with its length in two big-endian bytes and a one-byte frame type. Every instrument is subscribed twice, as a scrip topic (`sf|EXCHANGE|TOKEN`) and a depth topic (`dp|EXCHANGE|TOKEN`), up to 100 topics per request. Order and position updates come from `wss://<host>/realtime`, after a connection frame that is deliberately not JSON: `{type:cn,Authorization:<access token>,Sid:<session id>,src:WEB}`.

    **Peculiarities.**

    - Kotak assigns each session its own API host and returns it as `baseUrl`. A call to any other host is refused with stCode 200032 even when the token is valid, so no host is hard coded.
    - Kotak has no profile endpoint. The profile arrives only in the login answer, so every login writes `kotak:user:details` itself, and there is no `bin/kotak/user/details` script.
    - One quote socket carries at most 100 instruments, because every instrument takes two of the 200 subscriptions Kotak allows on one channel.
    - Its instrument files sit under a URL stamped with the day's date, so a missed download can never be fetched later.
    - It is one of four brokers whose order websocket also carries positions. It has no candle downloader.

    **Files.** `stock_brokers/api/kotak.py`, `stock_brokers/websockets/kotak.py`, `stock_brokers/instruments/kotak.py`, `stock_brokers/instruments/mapping/kotak.py` with `rules/kotak.yaml`, `stock_brokers/instruments/ticks/kotak.py`, `unified_broker_interface/utilities/broker_quotes/kotak.py`, `unified_broker_interface/utilities/broker_orders/kotak.py`, `bin/kotak/`, `services/kotak/`.

=== "Shoonya"

    **Login.** Shoonya is Finvasia's Noren deployment. `ShoonyaAPI` checks the session with `UserDetails`, including the `stat: ok` check in the body. To log in, it drives a headless Chrome through Shoonya's OAuth login page with the UCC code, password and current TOTP, reads the authorization code from the redirect, and exchanges it at `GenAcsTok` with a SHA-256 checksum of the vendor code, API secret and code.

    **Websockets.** Both sockets connect to `wss://api.shoonya.com/NorenWSTP/`, a separate connection each, so a market data reconnect can never drop an order event. The protocol is the same Noren JSON as Flattrade's: an `a` connect frame with `accesstoken`, a `d` subscription for depth and touchline, incremental `tk`/`dk` and `tf`/`df` frames, and `om` order messages.

    **Peculiarities.**

    - Because the login needs a headless browser, the quote sockets log in again one at a time, and only when nobody has already replaced the token.
    - The login body escapes `&` as `&`, because Noren splits the body on ampersands before parsing it, which breaks trading symbols such as `M&M`.
    - Shoonya allows about one REST request a second, and its candle downloader runs at 1 request a second.
    - Shoonya adjusts its price history inconsistently, so the unified price history does not use it as a source.
    - Shoonya and Wisdom Capital are the only brokers used for NCDEX quotes.

    **Files.** `stock_brokers/api/shoonya.py`, `stock_brokers/websockets/shoonya.py`, `stock_brokers/instruments/shoonya.py`, `stock_brokers/instruments/mapping/shoonya.py` with `rules/shoonya.yaml`, `stock_brokers/instruments/historical/shoonya.py` and `noren.py`, `stock_brokers/instruments/ticks/shoonya.py` and `noren.py`, `unified_broker_interface/utilities/broker_quotes/shoonya.py`, `unified_broker_interface/utilities/broker_orders/shoonya.py` and `noren.py`, `bin/shoonya/`, `services/shoonya/`.

=== "Stoxkart"

    **Login.** [`StoxkartAPI`][stock_brokers.api.stoxkart.StoxkartAPI] logs in again only when Stoxkart rejects the stored token as unauthorized. The login has three steps, with no browser: the client id and password go to `/auth/v2/login` for a register token, the current TOTP and that token go to `/auth/v2/twofa/verify` for a request token, and the request token is exchanged at `/auth/token` for an access token. The two version 2 steps carry a separate publisher key pair from the settings document.

    **Websockets.** Neither of Stoxkart's streams is documented for API users. Quotes come from the website's broadcast feed at `wss://broadcasting-v2.stoxkart.com/`, which takes no login, in a little-endian binary format: an 83-byte request header, then per instrument a trade subscription (code 12) and a depth subscription (code 23). Order updates come from `wss://openapi-v2.stoxkart.com/websocket/v2/connect`, after asking `websocket/authenticate` for a request id.

    **Peculiarities.**

    - Both streams read a synchronous connection in a loop of their own, so `StoxkartQuoteStream` and `StoxkartOrderSocket` are the only sockets that do not subclass `BrokerWebsocket`.
    - Stoxkart counts seconds from 1980-01-01, so 315,532,800 seconds are added to its timestamps.
    - Stoxkart keeps one order socket per client. A new connection closes the older one, so the socket waits five minutes before reclaiming it, and it and a logged-in website or app knock each other off at most that often.
    - Its pollers wait one second between requests, because Stoxkart documents a limit of one order book request a second.
    - It has no candle downloader and no REST quote source.

    **Files.** `stock_brokers/api/stoxkart.py`, `stock_brokers/websockets/stoxkart.py`, `stock_brokers/instruments/stoxkart.py`, `stock_brokers/instruments/mapping/stoxkart.py` with `rules/stoxkart.yaml`, `stock_brokers/instruments/ticks/stoxkart.py`, `unified_broker_interface/utilities/broker_orders/stoxkart.py`, `bin/stoxkart/`, `services/stoxkart/`.

=== "Wisdom Capital"

    **Login.** Wisdom Capital runs Symphony's XTS platform, which splits a broker into two applications with separate credentials and tokens. [`WisdomCapitalAPI`][stock_brokers.api.wisdom_capital.WisdomCapitalAPI] establishes both. The interactive token, for orders and the account, is checked with `GET /user/balance` and minted by posting the app key and secret to `https://trade.wisdomcapital.in/interactive/user/session`. The market data token, for quotes and charts, is minted from `price_api_key` and `price_api_secret` at `https://trade.wisdomcapital.in/apimarketdata/auth/login`.

    **Websockets.** A connection opens an Engine.IO session over HTTPS polling and then upgrades to a websocket with the `2probe` and `3probe` exchange. Quotes subscribe over REST for touchline (1501) and market depth (1502), and events arrive as socket.io frames `42["<event>", <payload>]`. Order updates join the interactive namespace with `apiType=INTERACTIVE`, which makes XTS push every order, trade and position event for the account.

    **Peculiarities.**

    - The host's certificate is issued to the platform provider's domain, so the websocket client pins the exact certificate instead of checking the hostname.
    - XTS issues one market data session per application key, and a second login invalidates the first, so the market data token is replaced under a Redis lock.
    - The profile endpoint allows about one call a day, which is why the token check uses the funds endpoint and `bin/wisdom_capital/user/details` fetches the profile once a day.
    - XTS counts seconds from 1980-01-01 in India time, and it misspells the last traded quantity as `LastTradedQunatity`.
    - It is one of four brokers whose order websocket also carries positions, and the only one besides Zerodha that reports a separate `day` positions list. It has no REST quote source.

    **Files.** `stock_brokers/api/wisdom_capital.py`, `stock_brokers/websockets/wisdom_capital.py`, `stock_brokers/instruments/wisdom_capital.py`, `stock_brokers/instruments/mapping/wisdom_capital.py` with `rules/wisdom_capital.yaml`, `stock_brokers/instruments/historical/wisdom_capital.py`, `stock_brokers/instruments/ticks/wisdom_capital.py`, `unified_broker_interface/utilities/broker_orders/wisdom_capital.py`, `bin/wisdom_capital/`, `services/wisdom_capital/`.

=== "Zerodha"

    **Login.** `ZerodhaAPI` probes `GET https://api.kite.trade/user/profile`. To log in, it drives a headless Chrome through `https://kite.trade/connect/login` with the username, password and current TOTP, reads the `request_token` from the redirect, and exchanges it at `https://api.kite.trade/session/token` with a SHA-256 checksum of the API key, request token and API secret.

    **Websockets.** Both sockets connect to Kite's ticker at `wss://ws.kite.trade`, with the API key and access token in the URL, so there is no login message. Quotes arrive as big-endian binary frames, and a packet's length says what it holds: 8 bytes for the last price, 28 or 32 for an index, 44 for a quote, and 184 for a full quote with five levels of depth. Kite has no separate order endpoint: order updates arrive as JSON text on the same ticker, so the order socket subscribes to no instruments and only order updates reach it.

    **Peculiarities.**

    - Kite issues one token per session and every login invalidates the previous one, so two independent logins break each other. The sockets and the candle downloader log in only when no other process has already replaced the token.
    - The low byte of an instrument token names its exchange segment (738561 is NSE RELIANCE), and prices are divided by 100, or by 10,000,000 for NSE currency and 10,000 for BSE currency.
    - The quote script subscribes to the whole instrument master over 24 sockets by default, more than Kite documents.
    - Zerodha is the only verified broker in the unified quote combiner, so it owns every instrument it streams, and its index history back to 2005 is the primary source for index prices.

    **Files.** `stock_brokers/api/zerodha.py`, `stock_brokers/websockets/zerodha.py`, `stock_brokers/instruments/zerodha.py`, `stock_brokers/instruments/mapping/zerodha.py` with `rules/zerodha.yaml`, `stock_brokers/instruments/historical/zerodha.py`, `stock_brokers/instruments/ticks/zerodha.py`, `unified_broker_interface/utilities/broker_quotes/zerodha.py`, `unified_broker_interface/utilities/broker_orders/zerodha.py`, `bin/zerodha/`, `services/zerodha/`.

!!! danger "The broker scripts log in to live accounts"
    Everything under `bin/<broker>/` reaches a real trading account, and several brokers log in by driving a headless Chrome and consuming a TOTP. Running a script repeatedly means authenticating for real each time.
