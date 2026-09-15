# Notes on `stock_brokers/api/stoxkart.py`

## History of the login

Until 2026-09-15 Stoxkart's API login never succeeded. The first step, `POST /auth/login` on the `api` platform, was refused with `E-010 Invalid X-API-Key`, and the same refusal came back for a valid key, an unregistered key and a random string, so it was a gateway-level rejection rather than a problem with the key. The app registration on the developer site showed "pending approval" at the time.

On 2026-09-15 the registration showed "approved", and `/auth/login` then accepted the password and answered "Please enter TOTP". The documented next step, `POST /auth/twofa/verify` with `client_id`, `req_token`, `action` and `otp` in the JSON body, answered HTTP 400 with a body of only `{"status":"error"}`. Stoxkart's login documentation at https://developers.stoxkart.com/api-documentation/login describes the password step and the token exchange but not the TOTP step, so the version 1 request had been inferred rather than documented.

## Why the login uses Stoxkart's version 2 endpoints

Stoxkart's own login page at `superrtrade.stoxkart.com/login` no longer calls the version 1 endpoints. Its JavaScript calls `/auth/v2/login` and `/auth/v2/twofa/verify`, sends an empty body, and carries everything in headers: `platform`, `client-id`, `password` or `second-auth-type` and `second-auth-value`, `registered-token`, `device-id`, `api-version`, `client-version`, and a publisher key pair in `x-api-key` and `x-api-secret`. The class copies those headers exactly, including `device-id: developer-portal` and `client-version: dev-portal`, because that is the combination that was verified live. The token exchange at `/auth/token` and every later request are unchanged from version 1.

The version 2 login answers the password step with `register_token` rather than `request_token`, and the TOTP step answers with `request_token`, `expiry_time`, `redirect_url` and `app_name`. The `redirect_url` and `app_name` are those registered for the app on the developer site.

## Why the publisher key pair is in MongoDB rather than in the code

The publisher key pair is not issued to the account. It is written in plain text in the JavaScript of Stoxkart's public login page. It is kept in the `stoxkart` settings document as `publisher_api_key` and `publisher_api_secret`, so that it stays out of git history and can be replaced without a code change if Stoxkart rebuilds its login page with a different pair. `_login_headers` raises a clear error when either field is missing, rather than sending an empty header and getting an unexplained refusal.

## Why the password and TOTP checks raise instead of branching

The login page shows a TOTP dialog when `is_2fa_enabled` is true and an SMS OTP dialog otherwise, and it redirects to a change-password page when `is_change_pwd_required` is true. Neither the SMS OTP nor a password change can be completed unattended, so the class raises with an explanation in both cases.

## Why the TOTP waits near the end of a window

A TOTP code generated in the last moments of its 30-second window can expire before Stoxkart checks it. How much clock drift Stoxkart tolerates is unknown, so `_current_totp` waits for the next code when fewer than five seconds are left.

## Why the Selenium fallback was removed

The browser fallback drove the same login page, which now uses the same version 2 endpoints, so it offered no path that the REST login does not. It also imported Selenium at module level, which every importer of this module paid for.

## The pre-production host

The login page's JavaScript points its API client at `https://preprod-openapi.stoxkart.com`. The class uses the production host `https://openapi.stoxkart.com`, which is where the version 2 login was verified.

## The account seen on 2026-09-15

`/funds` returned a cash balance of exactly 10000.0 with nothing used, and the app is registered as `Test1234` with `https://www.google.com` as its redirect address. Whether this is the real trading account or a test account had not been confirmed when the login was fixed.
