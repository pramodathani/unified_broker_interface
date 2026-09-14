# Known issues

Things that are wrong, unfinished or deliberately left alone, recorded so they are not
rediscovered from scratch. Everything here was true as of 2026-09-14.

## Storage

**`unified.broker_mappings` is not compressed.** It holds 45 million rows in about 11.7 GB with no compression
policy. One mapping date is added a day, so it grows by about
1.8 million rows a day.

## Correctness

**`bar_count` over-counts.** `_store` increments it by the number of rows written rather than by
the number of distinct new bars, so every overlapping forward window inflates it and the "bars
stored" figure from `bin/<broker>/historical_prices --status` drifts upwards over time. Row counts
taken from the table itself are unaffected. The fix is to count true insertions with
`RETURNING (xmax = 0)`, which touches the hot write path and was left alone deliberately.

**A series retired for having no bars is never revived.** The daily re-seed inserts with
`on conflict (instrument_token, "interval") do nothing`, so a contract that listed, was retired
for having never traded, and then started trading would stay retired forever. Clearing
`reached_broker_limit` where `limit_reason` names that case, periodically, would fix it.

**Fyers currency derivatives are left out of the unified quotes.** Fyers scales prices by a precision and
multiplier per instrument. A fixed divisor of 100 is right for two-decimal instruments and a hundred times
wrong for four-decimal currency pairs. `bin/fyers/quotes` divides by 10 to the precision times the
multiplier it reads from each snapshot, but `bin/unified/quotes` and `stock_brokers/instruments/ticks/fyers.py`
leave Fyers currency derivatives out until that scaling is confirmed on a live currency pair.

**Most unified tick normalizers are unconfirmed live.** Only Zerodha is verified, and Dhan agrees with it
on stored in-session MCX ticks but has no in-session NSE ticks stored. What Kotak, Flattrade, Shoonya,
Wisdom Capital, Fyers, Groww and INDmoney send was taken from stored weekend snapshots, a mock session
or the protocol, and the table in
[Unified scripts](../guides/unified-scripts.md#what-each-brokers-values-mean) marks which. Kotak's
timestamps are withheld entirely: its feed stamped RELIANCE's last update with a date and no time.

## Broker limits

**Flattrade permits one websocket per session.** Its market and order sockets each kicked the
other off on connect, both flapping in lockstep at close code 1000, while Shoonya runs both
happily on the same platform. `flattrade@order_updates` is left out of `flattrade.target` so
`flattrade@quotes` holds the connection, which makes Flattrade the one gap in the live half of the system. Noren can carry
order updates on the market socket, and that is the way to get both back.

**Stoxkart has no scripts but its instrument download.** Its REST authentication is unresolved on
the broker's side, so it has no `bin/stoxkart/` scripts beyond `instruments`. Its instrument master is a
public file, downloaded daily by `unified-instruments.service`, which is everything currently possible.

## Instruments deliberately excluded

**Dhan's NSE commodity segment** - segment `M` under `NSE`, some 23,700 option contracts. Dhan
lists them in its instrument master but its charting API publishes no exchange segment name for
them, so they cannot be requested.

**IND Money's BSE derivatives** - about 4,800 contracts. Both `BFO_` and `BSE_` prefixes are
refused with "Invalid scrip codes". If a third prefix turns up, adding it is one line in
`_scrip_prefix`.

**Stoxkart's NCDEX `TMCFGRNZM` option** - one row, on some dates. Stoxkart publishes it with
`expiry_date`, `strike_price`, `lot_size` and `tick_size` all empty, though `symbol_description`
still encodes them as `TMCFGRNZM08OCT26PE21800FO`. An option's identity is its underlying, expiry,
strike and type, so the mapping refuses to invent one and skips the row rather than give it a wrong
`instrument_id`.

This surfaces as `stoxkart ... 1 ROW ERROR(S)`, and it is expected output rather than something to
chase - five of the twenty-four dates stored in September 2026 carried it, one row each, out of
some eleven million Stoxkart rows. A row error on another broker, or a materially larger count on
Stoxkart, is a different matter and worth looking at.

It does expose a general gap worth knowing about: a row whose identity cannot be built is counted
as classified and then written nowhere, so it lands in neither a segment nor an uncategorised
bucket. The uncategorised design exists precisely so an unhandled row stays visible, and an
identity failure sidesteps it. Falling back to uncategorised on that failure would close it for
every broker at once, and is the shape of the fix if this ever matters more than five rows.

## Unverified

**Linger has to be proven across a reboot.** Every unit depends on `loginctl enable-linger` to keep
running after a logout and to start at boot. After enabling it on a machine, reboot and check that each
`<broker>.target` and `unified.target` come back on their own.

**Kotak and Fyers instrument downloads may need a session.** Only IND Money's does today, and
`bin/indmoney/instruments` logs in when its stored session is refused. If either download starts failing
after a token expiry, this is the first thing to look at.

## Observations, stored as received

**Wisdom Capital reports Saturday bars.** 2026-09-12 has five minute bars at tiny volumes on the
NSE cash segment, which no other broker shows for that date. Most likely a special session. It is
stored exactly as the broker sent it, which is the rule everywhere in this project - nothing is
derived, corrected or dropped on the way in.

**Zerodha reports some intraday volumes as negative numbers written unsigned.** The one deliberate
exception to storing values as received. Kite's 60, 30 and 15 minute candles for small NSE equities
in 2023 carry volumes such as `18446744073709449716`, which is −101,900 read as an unsigned 64-bit
integer; BLUECHIP-BE alone had five such bars between August and November 2023, and on 2026-09-14
77 series across 49 instruments were stuck on them. The value cannot be held by the `BIGINT`
`volume` and `oi` columns, and the refused insert rolled back the whole window, so the backward
walk could never get past it. [`BrokerCandles._store`][stock_brokers.instruments.historical.base.BrokerCandles]
now stores `NULL` for any volume or open interest outside the `BIGINT` range and logs a warning
naming the bar, keeping the bar's prices. Widening the columns to `NUMERIC(20,0)` would keep the
exact value, but would mean decompressing the 25 GB of compressed Zerodha chunks and changing
`unified.price_history` too.
