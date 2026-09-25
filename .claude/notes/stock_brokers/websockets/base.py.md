# Notes on `stock_brokers/websockets/base.py`

## Why there is a base class at all

Until 2026-09-25 every broker's quotes socket and order updates socket lived inside its script, and each carried its own reconnect loop. The architecture page called that a deliberate choice: self-contained scripts, no shared socket classes. When the sockets were moved into `stock_brokers/websockets/`, the user asked whether common code could go into a `base.py` the way `stock_brokers/api/base.py` holds `BrokerAPI`, provided it made the code simpler rather than more complicated.

The eighteen `run_forever` methods (every socket except Stoxkart's two) were then compared with their log strings removed. They turned out to be one mechanism: sixteen distinct control flows, most of them differing from Zerodha's by between zero and six lines, and INDmoney's quotes loop identical to Zerodha's. `close` was identical in seventeen of the eighteen. That is roughly 700 repeated lines, and the base class replaces them with about 60.

An earlier `stock_brokers/api` refactor had been reverted by the user because it moved copied code into a base class full of hook methods and class-attribute switches. The base here is kept to what the comparison showed is genuinely the same, and to two methods every subclass writes, `_connect` and `_log_in_again`, which mirror `BrokerAPI`'s `__init__` and `_request`.

## The differences the loops really had, and where each went

- How a socket logs in again differs per broker. Some sockets share a session object with a lock, others build a fresh API object. That is `_log_in_again`, written by every subclass.
- Dhan, Groww and Kotak quotes do not give up when refused straight after logging in again; they keep trying until six more connects have failed. That is the one overridable method, `_gives_up_after_logging_in_again`, which returns True by default.
- Fyers quotes pauses before connecting after a Cloudflare block or throttle, and Wisdom Capital orders waits for a replacement login after a `logout` event. Two cases did not justify a pre-connect hook in the base, so those two sockets keep a loop of their own in their own file.
- Groww orders caught its own `SocketRefused` inside the loop. That catch belongs in Groww's `_connect`, which sets the same flag.
- Flattrade, Shoonya and Kotak orders wrote the give-up test as `if logged_in_again:`, the rest as `if logged_in_again and (refused or failed >= 6):`. Those behave identically, because the surrounding `if` already requires `refused or failed >= 6`.

Stoxkart's two sockets are built differently, on a synchronous `create_connection` loop with their own silence and eviction handling, and have no `run_forever` to share. They do not subclass `BrokerWebsocket`.

## Why some log lines changed wording

The loop logs with one wording built from the socket's name, where the old loops had several. The give-up line reads "still cannot connect after logging in again", which is accurate both for a refused handshake and for connects that keep failing; the old quote loops said "is still refused" and the order loops "are still refused". The login-failure line no longer names the broker, because the logger's name already does (`zerodha.websocket_quotes`). The order sockets are named "Order updates socket", so their lines read "Order updates socket disconnected" where they used to read "Order updates disconnected". These are the only changes the offline recording in `test_runs/websocket_feeds/` shows for the loop; every Redis command, frame, login and wait is unchanged.
