# Pitfalls

Every entry on this page passed code review and then failed against the live system. They are
recorded because each one is invisible in the code that causes it - the wrong version reads as
correct, and only running it against a real broker says otherwise. All of them are fixed; the point
is not to write them again.

## Shutdown and restarts

**A drain loop must count rows read, not rows written.** A persister whose drain step returns the
number of rows it persisted sees a final batch of unusable records as an empty queue and exits the
loop - leaving the usable rows queued behind them, which are then never written at all. The loop
condition is "did I take anything off the queue", not "did I store anything".

**Signal handlers have to be installed before the threads start.** A `join()` with correct SIGTERM
handling is never reached when the entry point starts its threads first. Install the handlers, then start the
threads.

**`.venv/bin/python` is a symlink to the system interpreter.** The `bin/` commands re-exec
themselves under the virtualenv, and a guard that decides whether the re-exec already happened
by comparing resolved interpreter paths finds them equal, so the switch silently never happens and
the commands run against system site-packages. Compare `sys.prefix`.

## Sessions and logins

**A login attempt is not a login success.** A rate limiter keyed off a single
marker lets a login unit record an attempt and makes every script starting a second later hit the limiter
and sleep for 299 seconds before doing anything. The usual outcome of `ensure_session` is a cheap probe
that writes nothing to MongoDB, so an attempt marker alone cannot tell "the probe succeeded" from "the
login failed". `ensure_session` keeps two markers, `ubi:login-attempt:<broker>` and
`ubi:login-ok:<broker>`, and only genuine retries are rate limited.

**A lock holder that died still holds the lock.** Killing a process inside `ensure_session` -
before its own signal handlers exist - leaves `ubi:login:<broker>` held for its full 300 second TTL,
and every other process waits it out. The lock records the holder's pid, and a lock whose pid is gone is
released rather than waited for. `ensure_session` is what `BrokerCandles` and IND Money's instrument
ingester log in through by default; the `bin/<broker>/` scripts log in through the broker's API class.

## The candle queue

**The backward walk has to finish before any forward fill.** Preferring a forward fill whenever
the newest stored bar is older than today is reasonable-looking and deadlocks: outside market
hours the newest bar is always older than today, so the series re-asks the same empty recent
window forever and never walks back. See
[Walking backwards, then forwards](../guides/price-history.md#walking-backwards-then-forwards).

**Finishing a backfill is not retiring a series.** Reaching the broker's earliest date means
there is no more past, not that the instrument is dead - the series must keep collecting forward.
`_finish_backfill` and `_retire` are separate for that reason.

**A throttle says nothing about the series.** Recording each of Dhan's refusals as a series failure
pushes perfectly good series an hour into the future for something that is purely about the pace. A
throttle backs the rate limiter off and leaves the series claimable.
Dhan refuses five requests a second whatever its documentation says: twenty five requests at five
a second were throttled four times, at three a second none were.

**A broker can send the same bar time twice in one window.** Dhan does, and Postgres refuses a
batch that touches the same row twice - `ON CONFLICT DO UPDATE command cannot affect row a second
time`. The exception came out of `_store`, past `visit`, and ended the run. Bars are collapsed on
time before the write, last one winning.

**The write has to be inside the per-series guard too.** `visit` guarded the fetch and the parse
but not the store, so the failure above took the whole process down - and because the same window
is claimed again on restart, it would have taken it down every ten minutes for as long as the
service stayed enabled. An unexpected failure costs the series, not the run.

**A single impossible count fails the whole window, every time.** Kite sent volumes above
2⁶³ − 1 for a handful of 2023 intraday bars, Postgres refused the batch with
`bigint out of range`, and the window rolled back. Because the next attempt asks for the same
window, the series never moved again - 77 of them stopped at the same July 2024 boundary, while the
parser tests passed, since they never see such a value. Counts outside the `BIGINT` range are stored
as `NULL` with a warning; see [Known issues](known-issues.md#observations-stored-as-received).

## Writing to the database

**`execute_values` pages internally, so `cursor.rowcount` reports only the last page.** A seed
that registered 1,149,064 rows announced itself as having written 22,964. Count what was passed
in, not what the cursor says afterwards.

**Chunk size is measured, not guessed.** Seven day chunks for `price_history` put two decades of
one instrument's daily bars across 1,133 chunks of 98 rows each, where the per-chunk overhead
dwarfed the data: 75 MB for 111,000 bars, against 35 MB for the same data in one month chunks.

## Feeds, one refusal per broker

Every one of these is a broker refusing a connection in a way that reads as something else, and none
of them shows up while only Zerodha is tested.

**A token is not always a number.** Only Zerodha's subscription tokens are integers; every other broker
carries a segment - `NSE_EQ:2885`, `NSE|2885`, `NSE|CASH|2885`, `1:2885`, `NSE:SBIN-EQ` - so a feed that
discards every token it cannot parse as an integer starts, subscribes to nothing, and exits quietly at
eight of the nine brokers.

**Noren's connect frame is `t` of `a` and the token is named `accesstoken`.** Sending `t` of `c`
with the token as `susertoken` is parsed and refused with `NOT_OK`, which is indistinguishable
from an expired session and is not one - the same token authenticates REST happily. Verified
against both Flattrade and Shoonya.

**Kotak's `sfeed` answers a subscription with one stale snapshot and then nothing.** Until 2026-09-15
`bin/kotak/quotes` used `wss://sfeed.kotaksecurities.com/apifeed`, which authenticated, acknowledged the
subscription, sent one snapshot and stayed connected without a further tick. The snapshot carried
Friday's prices with zero volume, and more arrived only at session boundaries, so the stream held a few
dozen ticks a day and looked like a quiet feed rather than a broken one. In the same minute the HSM feed
of Kotak's SDK, `wss://mlhsm.kotaksecurities.com`, updated every instrument every second. Before trusting
a feed, compare its last price and volume with another broker's during the session.

**Kotak's HSM feed asks for acknowledgements.** Its connection reply carries a count (five on
2026-09-15), and every data frame then starts with a message number; after that many frames the client
must send an acknowledgement frame with the last number. A decoder that does not expect the message
number reads it as the packet count.

**Kotak's MCX quantities are all in Kotak's lots.** On the HSM feed volume, open interest, total buy and
sell quantity, last quantity and every order book quantity are lots times Kotak's own lot size - 100 for
CRUDEOIL, 1250 for NATURALGAS, 1 for GOLD, whose contract lot is 100 grams. GOLD alone therefore looks
like plain lots, which is how the older feed's figures were misread.

**Wisdom Capital's interactive socket needs `apiType=INTERACTIVE` in its socket.io query.**
Without it the namespace answers "Socket joined successfully!" and the server closes the
connection exactly ten seconds later, every time, at every heartbeat rate and with every user
identifier the login offers. The "Your session has been expired" that arrives alongside the join
is noise - it appears for a token minted a second earlier.

**INDmoney's price feed sends JSON inside a JSON string.** Every update is a line such as
`"{\"mode\":\"full\",\"instrument\":\"11536\",...}"`, so one `json.loads` returns a `str`. `bin/indmoney/quotes`
treated anything that was not a dict as a heartbeat and skipped it quietly, and for at least the five days to
2026-09-15 the feed connected, subscribed and streamed about ten updates a second while `indmoney.ticks` stayed
empty. Decode a string result a second time, and log a message you skip rather than dropping it silently.

**INDmoney's `close` is the last price.** In `quote` and `full` mode the feed's `close` moves with every trade and
equals `ltp`; the previous close is not on the feed at all. `quote` mode has no `ltp`, which made `close` look like
the only price.

**Wisdom Capital's interactive socket must not log in for itself.** XTS keeps one interactive session per
application key, so a login by the socket logged out the token the pollers share, the pollers logged in again, and
their login logged out the socket. The socket then received `logout` ("You have been logged out by another user.")
and stayed connected while delivering nothing, which looks exactly like a quiet account. From 2026-09-14 to
2026-09-15 it merged no updates at all. It now joins with the shared `last_login` token, taking the user id from the
token's payload, and treats `logout` as a reason to reconnect with whatever login replaced it.

**XTS states two heartbeat numbers and they disagree.** The server says how often it wants to
hear from us and how long it will wait, and market data asks every 20s while waiting 60s where
interactive asks every 25s but waits only 20s. Pacing on `pingInterval` alone heartbeats every
23s into a 20s patience. Use half the shorter of the two.

## Platform notes

- `add_columnstore_policy` is a **procedure** (`CALL`); `compress_chunk` is a **function**
  (`SELECT`). Same extension, opposite conventions.
- `load_dotenv()` resolves `.env` from the module's directory rather than the working directory,
  which is why cron and systemd need no `WorkingDirectory`.
- systemd **user** units want `WantedBy=<broker>.target` or `WantedBy=unified.target`, and each
  target wants `WantedBy=default.target` - **not** `multi-user.target`, which does not exist in the
  user manager and would silently never start anything.
- `StartLimitIntervalSec=0` on every long-running unit, or a briefly unreachable Redis or a broker
  outage leaves one failed permanently. The login units are the exception on purpose: three tries an
  hour.
- A feed unit and its persister need no `After=` ordering between them: a Redis Stream keeps its
  entries, up to its cap, until the persister reads and acknowledges them, so whichever stops first
  loses nothing. See
  [Running it as a service](../guides/services.md).
- NSE and BSE equity close at 15:30 IST but **MCX trades to 23:30**, so use MCX futures to
  exercise a live feed in the evening.
- Tested against TimescaleDB 2.30, PostgreSQL 18.6, Redis 8.10.1 and Python 3.14 on Ubuntu 26.04.
