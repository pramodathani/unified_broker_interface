# stock_brokers/api/flattrade.py

## Why an empty token raises

On 2026-10-27 `trade/apitoken` answered without a `token` field (Flattrade had refused the request code with `Invalid Input : INVALID_SESSION`). The old code took `token_data.get("token", "")` and wrote the empty string to MongoDB and the Redis `last_login` hash. Every process then probed `UserDetails` with an empty `jKey`, got `Session Expired : Invalid Session Key`, and ran its own login, so a single bad answer turned into thousands of logins a day. The constructor now raises `FlattradeAPIException` instead, and the stored token is left as it was.

## Why every login request has a timeout

`requests` waits forever without one. A broker that accepts the connection and never answers would freeze the constructor, and with it the service, without an exit for systemd to restart. `LOGIN_TIMEOUT_SECONDS` is 10, the same as the scripts' own `TIMEOUT_SECONDS`.
