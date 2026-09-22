# Notes on `stock_brokers/api/wisdom_capital.py`

## Why the class establishes two sessions

Wisdom Capital runs Symphony's XTS platform, which splits a broker into two applications with separate credentials. The interactive application places orders and reports the account; the market data application serves quotes and charts. Each issues its own token and refuses the other's, so a Wisdom Capital process that wants both quotes and orders needs both tokens.

Until 2026-09-22 only the interactive token was established here, and the market data token was minted by whoever happened to need it. Three copies of that login existed: one in `stock_brokers/instruments/historical/wisdom_capital.py`, which published into `ubi:session:wisdom_capital:marketdata` through `shared_application_session`, and two identical copies in `bin/wisdom_capital/instruments/price_history` and `bin/wisdom_capital/instruments/websocket_quotes`, which published into `wisdom_capital:session:marketdata`. Because the candle class and the two scripts used different Redis keys, a candle downloader running through the class and a live quotes feed could not see each other's token and invalidated each other whenever both minted. Constructing the API class now establishes both sessions, stores them in the one `last_login` document, and the three copies were deleted.

## Why a new market data token is not minted on every construction

XTS issues exactly one market data session per application key: a second login invalidates the first token rather than handing out a second. Every long-lived Wisdom Capital script constructs this class, and several reconstruct it whenever a request is refused, so minting on construction would have the order poller quietly killing the live quotes feed's session. The stored token is therefore checked and reused, and a new one is minted only by `replace_market_data_session`, under the Redis lock `wisdom_capital:session:marketdata:lock`, by whoever found the stored one unusable.

## Why the checks use the balance and the client configuration

The interactive token is checked with `GET /interactive/user/balance` rather than `/user/profile` because Wisdom Capital allows only about one profile call a day, which is a budget an object constructed several times a day cannot live inside. The funds endpoint authenticates identically, so it proves the same thing without spending that allowance. The market data token is checked with `GET /apimarketdata/config/clientConfig` for the same reason: it is the cheapest market data call that has to authenticate. The chart endpoint cannot be used as a check, because it answers an unknown instrument, a window before the history begins and an expired token all with the same empty success.

## Why a failed market data check keeps the token

`_market_data_token_works` treats only an explicit refusal - HTTP 401, or a body naming `e-session`, `e-token` or an invalid token - as proof that the token is dead. A timeout, a bad gateway or an unexpected status is read as "cannot tell", and the stored token is kept with a warning. Minting a replacement invalidates whatever the live quotes feed and the candle downloader are holding, which is too destructive to do on the strength of a transport error. A token that really has died is still caught, because the consumer whose request is refused calls `replace_market_data_session` with the token that failed.

## Why a rate limit counts as a working session

Wisdom Capital rate limits on a rolling window regardless of endpoint, and the limiter runs only after the request has authenticated: its error names the authenticated user. So HTTP 429, or a code containing `e-apirl`, proves the token is good rather than bad. An expired or missing interactive token instead comes back as `e-token-0002`, "Please Provide token to Authenticate". A previously failed login stored the string "None" rather than a token, which is why both checks test for that string as well as for an empty value.

## Why a market data failure is recorded rather than raised

Eight of the twelve Wisdom Capital scripts - the order pollers, the portfolio pollers, the user details poller - never touch the market data application. If the constructor raised when the market data credentials were missing or the market data login failed, a credential none of them use would stop all of them. The failure is therefore kept in `market_data_session_error` and logged as a warning. `bin/wisdom_capital/session/connect` raises it, so the morning login unit still fails loudly and systemd still retries, and the consumers that genuinely need the token raise when they ask for it.

## Why logins merge into the stored document

The two tokens are minted by different paths, at different times, and often in different processes. `_store_login` therefore reads the login in force, merges the new fields into it, and writes MongoDB first and Redis second. A plain replace would erase the other application's token every time one of them logged in. The interactive login stamps `last_login` and the market data login stamps `market_data_last_login`, so the timestamp `BrokerAPI._current_login` compares still means "when the interactive session was established".

## Why the certificate is not verified

`trade.wisdomcapital.in` is served off Wisdom Capital's white-label provider and presents that provider's certificate, `CN=*.ashlarindia.com`, which does not cover the `wisdomcapital.in` name, so verification fails on the name check for every call. Wisdom Capital is the only broker in this project with a broken certificate, so `_VERIFY_SSL` is a class attribute rather than a global setting, and `_request` applies it only when the caller said nothing about `verify`, so an explicit `verify=` from a caller still wins. Third-party hosts used during the legacy login, such as `developers.symphonyfintech.in`, present valid certificates and stay verified. The module calls `urllib3.disable_warnings` because the insecure-request warning would otherwise be printed on every single call. Flip `_VERIFY_SSL` back to True once Wisdom Capital fixes the certificate.

## Why the Selenium login is still here

The ordinary interactive login is a direct session request: the app key and secret are posted to `/interactive/user/session`, with no browser and no PIN. `_USE_LEGACY_LOGIN` keeps the older flow, which drives the web login page with a headless Chrome, scrapes the access token out of a `<pre>` tag on the page it lands on, and adds that token and a unique key from Symphony's host lookup to the session request. It is kept as a fallback in case the direct endpoint stops working; flip the flag to use it.
