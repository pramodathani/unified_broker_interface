# Notes on `stock_brokers/websockets/wisdom_capital.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/wisdom_capital/instruments/websocket_quotes` (`WisdomCapitalSession`, `pinned_request`, `is_authentication_refusal`, `is_already_subscribed`, `first_json_object`, `QuotesSocket`, `levels` and `true_epoch`) and `bin/wisdom_capital/orders/websocket_order_details` (`pinned_get`, `first_json_object` and `OrderUpdatesSocket`). The offline recording in `test_runs/websocket_feeds/` reproduces every HTTPS request, frame, tick and order and position write.

## Refreshing the certificate pin

`CERTIFICATE_FINGERPRINT` is the SHA-256 of the certificate `trade.wisdomcapital.in` served, valid to 2027-01-20. When Wisdom Capital renews it, both sockets refuse the new certificate and log the fingerprint they were shown. The current fingerprint can be read with:

    echo | openssl s_client -connect trade.wisdomcapital.in:443 2>/dev/null | openssl x509 -noout -fingerprint -sha256

The pin replaces a hostname check because the host's certificate is issued to the platform provider's domain rather than to `trade.wisdomcapital.in`.

## Why the XTS mechanics are one class

The two old scripts each carried their own copy of the pinned HTTPS request, `first_json_object`, the Engine.IO handshake, the certificate check and the heartbeat thread. `WisdomCapitalTransport` holds one copy, used by both sockets. The market data socket's request sent an `authorization` header and a JSON body; the interactive socket's GET sent neither. One `request` method covers both, since urllib3 treats a missing body and `body=None` alike and the header is added only when there is a token.

## Why there are two session classes

The two sockets use `WisdomCapitalAPI` differently. The quotes socket reads the market data token and asks the API to replace it when refused, and must fail to start when the API recorded a market data login failure. The order socket reads the interactive token, takes the user id from its JWT payload, and on a refusal constructs the API again. The order socket must also start when the market data login failed, because it never uses that session. One class with both behaviours would need a switch, so there are two.

## Why the order socket keeps its own reconnect loop

After XTS logs the interactive session out, the socket closes and waits up to ten seconds for the login that replaced it to reach Redis, and treats a token that is still the logged-out one as a refused session. That step sits between connecting and deciding whether to log in again, in the middle of the loop, so `WisdomCapitalOrderUpdatesSocket` overrides `run_forever` with the base loop plus that step, rather than the base class growing a hook for one broker. Its log lines use the base loop's wording.

## Test notes

The subscription snapshot is gathered into a set before its ticks are handed on, exactly as the old code did, so the order of a snapshot's ticks follows Python's string hashing and can change from one process to the next. The recorded scenarios subscribe snapshots for one instrument at a time for that reason. Every scripted connection that starts a heartbeat thread ends with a close, so no thread outlives its scenario.
