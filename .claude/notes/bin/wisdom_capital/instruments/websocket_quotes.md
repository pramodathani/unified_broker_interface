# Notes on `bin/wisdom_capital/instruments/websocket_quotes`

## Why an already-subscribed answer is not treated as a refused token

XTS reports instruments that are still subscribed on the current market data session as `e-session-0002`, with the description `Instrument Already Subscribed !` and a result carrying `Remaining_Subscription_Count`. The code's `e-session` prefix is the same prefix a genuinely refused token carries, but the answer proves the opposite: the request authenticated, and the platform is declining it only because the subscription exists already.

This matters because the subscription belongs to the market data session rather than to the socket. Restarting the service during market hours leaves the previous process's subscription registered, so the first thing the new process sees is that answer. Until 2026-09-22 the script matched on the prefix alone, concluded the token was dead, and replaced it. XTS issues exactly one market data session per application key, so that replacement invalidated the token every other Wisdom Capital process was holding: on the restart at 22:19:13 that day the candle downloader was refused in the same second and had to log in again before it could continue.

The script now drops the stale subscription with `PUT /apimarketdata/instruments/subscription` and asks to subscribe again, which yields a proper snapshot on a session that is already good. The old behaviour is kept as the fallback: if the second attempt is refused as well, the token is replaced exactly as before, so the worst case is what used to happen every time.

## Why the market data token comes from `WisdomCapitalAPI`

The token used to be minted here, in a copy of the same login that `bin/wisdom_capital/instruments/price_history` carried, published under the Redis key `wisdom_capital:session:marketdata`. Since 2026-09-22 constructing `WisdomCapitalAPI` establishes both of Wisdom Capital's sessions and publishes the market data one in the shared `last_login` document, so this script reads `market_data_access_token` and `market_data_user_id` from there and asks that class to replace a refused token. The lock `wisdom_capital:session:marketdata:lock` is still the thing that keeps two processes from minting at once, and it now lives in the API class. See the note beside `stock_brokers/api/wisdom_capital.py`.
