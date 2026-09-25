# bin/wisdom_capital/orders/websocket_order_details

## Why the socket uses the shared login instead of its own

Until 2026-09-15 every connection posted `api_key` and `api_secret` to `/interactive/user/session` and joined with the token that came back. XTS keeps one interactive session per application key, so that login logged out the token held in the Redis `last_login` hash. The pollers (`orders`, `positions`, `trades`, `funds`) saw `e-session-0005` within a second, logged in again, and their login logged the socket out. XTS then pushed a `logout` event and kept the connection open, heartbeats included, while delivering no order or position events. The journal from 2026-09-14 14:21 to 2026-09-15 09:40 shows two connections, both logged out in the second they joined, and no merged updates.

The socket now reads the token through `WisdomCapitalAPI._current_login()`, which is the same lookup every REST request makes, so all Wisdom Capital processes send one token.

## Where the user id comes from

The socket.io query needs `userID`. The login response carries it, but `WisdomCapitalAPI` stores only `access_token` in `last_login`. The token is a JWT whose payload has a `userID` claim, so `_user_id_from_token` decodes the payload without verifying the signature. Verification is not needed because the server checks the token itself; the claim is only echoed back in the query. The claim does not equal `ucc_code` from the settings, so the settings cannot be used instead.

## Why the socket waits after a logout

The logout reaches the socket at the moment another process's login succeeds at XTS, but that process writes MongoDB and then Redis only after its HTTP response returns. If the socket compared tokens straight away it would usually still see the old token, decide the session was dead, and construct `WisdomCapitalAPI`. If that construction's probe also ran before the new token reached Redis, it would log in and restart the ping-pong. `_wait_for_replacement_login` polls the shared login once a second for up to `REPLACEMENT_LOGIN_WAIT_SECONDS` (10) and reconnects as soon as the token changes.

If the token never changes, for example because something outside this project logged in with the same application key, the socket falls back to the existing path. `WisdomCapitalAPI()` probes the stored token with `GET /user/balance` and logs in only if the probe fails. A second logout straight after that sets `gave_up`, the script exits 1, and systemd restarts it 15 seconds later, so a persistent outside login costs one reconnect cycle every 15 seconds or so rather than a tight loop.

## Why only the event named `logout` is handled

`docs/contributing/pitfalls.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/pitfalls.md`) records a "Your session has been expired" message that arrives alongside the join when `apiType=INTERACTIVE` is missing, and that message is noise. Every event the socket has logged under `apiType=INTERACTIVE` is either `joined` or `logout` with "You have been logged out by another user.", so matching the event name exactly avoids reacting to anything else.

## How it was checked

An offline harness in the session scratchpad loaded the script with `SourceFileLoader`, replaced `pinned_get`, `websocket.WebSocketApp` and the API class with fakes, and ran the real `run_forever` through three cases: a logout followed by a new token (reconnects with the new token and never constructs the API), a logout with an unchanged token (constructs the API once), and no stored token at first (constructs the API once, then connects). `_user_id_from_token` was also checked to return a user id for the real stored token and None for malformed tokens.

## Where the socket went

On 2026-09-25 the socket this note describes moved out of the script into `WisdomCapitalOrderUpdatesSocket` in `stock_brokers/websockets/wisdom_capital.py`, which also has a note of its own. The script now writes to Redis what the socket hands it. Where this note names the old class or function, the same code now lives there, and the offline recording in `test_runs/websocket_feeds/` shows the move changed nothing the script writes to Redis.
