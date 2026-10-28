# bin/indmoney/instruments/websocket_quotes

## Why no INDmoney tick was stored

On 2026-09-15 `indmoney.ticks` had no rows in the previous five days and `indmoney:quotes:stream` existed but was empty, while the service had been connected since 2026-09-14 14:21 and reconnected only ten times. A raw probe with the same headers and subscription at 10:31 IST received 119 frames in 30 seconds for two instruments. Each frame was a JSON string literal containing JSON, followed by a newline:

```
"{\"mode\":\"quote\",\"instrument\":\"11536\",\"timestamp\":1789448499944,\"data\":{\"open\":2275.5,\"high\":2322.4,\"low\":2270,\"close\":2301.3,\"volume\":2389535}}"
```

`json.loads` returned a `str`, the old `parse_ticks` wrapped it in a list, skipped it as "not a dict", and the comment called such messages heartbeats and acknowledgements. The only log line for skipped frames was at debug level, and only for frames that were not JSON at all, so nothing was ever logged. `_decode_entries` now splits a frame into lines and decodes a string result a second time, and `parse_ticks` logs any message without instrument data at info level.

## Why `full` mode

The same probe tried each mode for five to eight seconds on TCS:

| Mode | Fields in `data` |
| --- | --- |
| `ltp` | `ltp` |
| `quote` | `open`, `high`, `low`, `close`, `volume` |
| `full` | `ltp`, `ltt`, `volume`, `total_buy_qty`, `total_sell_qty`, `ask_price`, `bid_price`, `oi`, `open`, `high`, `low`, `close` |
| `depth`, `market_depth`, `depth5`, `snapquote`, `greeks` | nothing arrived |

The old script subscribed in `quote` mode, which has no last price at all; its `close` moves with every trade and equals the last price, which is how it could be mistaken for a price field. `full` is the only mode with a last price and quantities. The old field spellings (`ltq`, `atp`, `tbq`, `bids`, `prev_close` and others) were guesses from before any data was seen; they were replaced by the measured names.

## Why `change` is None and `ohlc.close` is kept as sent

The feed carries no previous close, so a change computed against its `close` would always be zero. `change` is left `None` and the unified layer computes it from an earlier owner's previous close. `ohlc.close` still holds the feed's value as sent, because the project stores broker data unaltered and the normalizers' `CLOSE_NEVER` policy already keeps it out of the unified quote.

## Why one segment per socket

Updates name the instrument by bare security id (`"instrument":"11536"`), not `NSE:11536`. `_subscribed_token` recovers the segment from the socket's own subscription. INDstocks ids did not collide across segments on 2026-09-13, but nothing guarantees it, so `main` groups instruments by segment before batching and a bare id can then match only one token.

## Why the depth has a price and no quantity

`full` mode gives the best bid and ask price only. They are written as one level each side with `quantity` and `orders` `None`, so they reach `indmoney.ticks` as `bid1_price` and `ask1_price`. The unified `_levels` drops levels without a quantity, so they do not enter the unified quote.

## How it was checked

An offline check parsed the captured `full` frame as a string, a two-line frame as bytes, a message without data and a line that is not JSON. A live check at 10:36 IST ran `QuotesSocket` for 45 seconds with an in-memory stand-in for Redis, without logging in, and got 441 ticks for the five subscribed NSE stocks. Against Zerodha's last tick at the same moment, last prices, open, high and low matched; INFY and ICICIBANK volume matched exactly and TCS by one share; the last trade time matched within three seconds and the exchange timestamp within two. The median delay from exchange timestamp to receipt was 0.8 seconds, which is why both normalizers now trust both times.

## Where the socket went

On 2026-09-25 the socket this note describes moved out of the script into `IndmoneyQuotesSocket` in `stock_brokers/websockets/indmoney.py`, which also has a note of its own. The script now writes to Redis what the socket hands it. Where this note names the old class or function, the same code now lives there, and the offline recording in `test_runs/websocket_feeds/` shows the move changed nothing the script writes to Redis.

## Why an empty subscription set waits instead of exiting

From 2026-10-27 the quote allocator decides which instruments each broker streams. INDmoney has preference 6, below every other broker, because only one of its sockets could be relied on, so on 2026-10-28 it was given 0 instruments and its subscription set was empty. The script then exited 2, which the unit treats as a bad argument and does not restart, so `indmoney-instruments@websocket_quotes.service` showed as failed every day although nothing was wrong. Exiting 0 instead would not help: the unit restarts on every exit other than 2, so the script would start again every 15 seconds. Stopping the unit from the allocator would not help either, because `bin/check-services` starts every stopped long-running service again.

The script therefore waits, without logging in or opening a socket, until systemd stops it. The allocator's `--restart-feeds` restarts a feed whenever its set or socket size changes, so the day INDmoney is given instruments, the restart brings them in. Only an empty set waits: `--tokens` that resolve to nothing is still a mistake by whoever typed it, and still exits 2.
