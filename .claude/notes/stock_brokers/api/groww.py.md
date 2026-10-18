# Notes on `stock_brokers/api/groww.py`

## The login storm of 2026-10-18

`groww-login.service` failed three times from 07:00 with Groww's "429 Rate limit has breached for your request". The login itself was not at fault: it had worked on the 15th, 16th and 17th. Three things together used up the account's request limit.

1. Groww's access token expires at 06:00. Every Groww script builds its own `GrowwAPI`, so all of them found the session dead in the same second, and each constructor asked Groww for its own token.
2. A token answer whose `error` lacked Groww's usual `code` and `message` made `_request` fall through and return `None`. The constructor then failed with `TypeError: argument of type 'NoneType' is not a container or iterable`, which hid Groww's actual answer, so it is still unknown why the 06:00 token requests were refused.
3. The Groww units restart every fifteen seconds with no start limit (`StartLimitIntervalSec=0`), and the order socket was already restarting every few seconds because of the repeated `INFO` described in the websocket note. Between 05:00 and 07:10 each poller restarted about 260 times and the order socket 455 times, and every restart probed Groww and asked for a token again.

On the 17th one script got a token at 06:00:00, which ended the storm; on the 18th none did, Groww limited the account, and the scripts kept it limited.

## What changed

- **Every error status raises.** `_refusal` builds the exception for any status of 300 or more. Groww's `error.code` and `error.message` are used when both are there; otherwise the HTTP status is the code and the whole body the message. `GrowwAPIException.status_code` always carries the HTTP status, because `code` is Groww's own code when it gave one (such as `GA005` for a refused token), and the constructor needs the HTTP status to tell a dead session from anything else.
- **A 429 stops every process.** It is recorded in `groww:api:blocked-until` for five minutes, and `_request` refuses to send anything while the key holds a later time, raising `GrowwBlockedError`. A cache that cannot be read never stops a request, which also keeps the existing example programs, whose stand-in caches have no `get`, working unchanged.
- **The constructor logs in only after a 401**, or when there is no stored login at all (`KeyError` or `TypeError` while building the request). Before, any failure of the probe led to a login, including a 429 and a network error, which is the pattern Fyers moved away from after its Cloudflare bans.
- **One token request at a time, at most once a minute.** `_log_in` takes `groww:login:token-lock` with `NX`. The holder first checks whether another process has already stored a login newer than the one that failed, and uses it if so; otherwise it records the attempt in `groww:login:token-attempt` and asks Groww. A process that cannot take the lock polls every two seconds for up to a minute for a newer login.

## Why not `ensure_session`

`stock_brokers/api/utilities/session.py` already has a cross-process login lock, but it works by constructing the broker's API class, so it cannot be called from inside `GrowwAPI`'s own constructor, which is where every Groww script, the Groww websocket session and `bin/groww/session/connect` log in. Its lock key `ubi:login:groww` is also held while it constructs `GrowwAPI`, so taking that same key inside the constructor would wait on itself. The token lock here is a separate, narrower key around the one request that matters.

## Test notes

The example programs under `examples/stock_brokers/api/groww/` never call the real constructor and patch `requests.request`, so nothing reaches Groww. `GrowwBlockedError/example_1` and `example_2` show the limit, `GrowwAPIException/example_3` the error shape that used to return `None`, and `GrowwAPI/example_3` two scripts sharing one token request. They use stand-ins for Redis and MongoDB. The five-minute block's log line carries the time of day, but it goes to standard error, which the example runner does not compare.
