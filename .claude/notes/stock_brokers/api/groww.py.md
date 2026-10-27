# stock_brokers/api/groww.py

## Why the token probe and token request have a timeout

On 2026-10-25 between 13:59 and 14:03 IST, six Groww services (`portfolio@funds`, `portfolio@holdings`, `portfolio@positions`, `orders@api_order_details`, `orders@api_trade_details`, `user@details`) entered `GrowwAPI()` and never came back. Each held an open HTTPS connection to Groww and logged nothing for two days, while systemd showed them as running. The probe of `/v1/user/detail` and the `POST /v1/token/api/access` had no timeout, so `requests` waited forever. Both now use `LOGIN_TIMEOUT_SECONDS` (10), so a silent Groww makes the constructor raise and the service exit for systemd to restart.
