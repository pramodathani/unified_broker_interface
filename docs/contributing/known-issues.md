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

**Wisdom Capital's pollers log in independently when the session expires.** `bin/wisdom_capital/orders`,
`positions`, `trades` and `funds` each construct `WisdomCapitalAPI` when their token is refused, and XTS allows one
interactive session per application key, so four logins in the same second can log each other out. On 2026-09-15
they did this twice, at 06:36:07 and 06:36:20, before settling on one token. The interactive login has no
cross-process lock like the market data login in `bin/wisdom_capital/quotes`, and adding one to `WisdomCapitalAPI`
would change every Wisdom Capital script, so it was left alone.

**Kotak streams no index values.** `bin/kotak/quotes` subscribes scrip and depth topics only. Kotak's HSM
feed serves indices as separate `if|` topics named by the index's name, which the script's `EXCHANGE|TOKEN`
validation rejects, and those topics' fields have not been measured live.

**Fyers currency derivatives are left out of the unified quotes.** Fyers scales prices by a precision and
multiplier per instrument. A fixed divisor of 100 is right for two-decimal instruments and a hundred times
wrong for four-decimal currency pairs. `bin/fyers/quotes` divides by 10 to the precision times the
multiplier it reads from each snapshot, but `bin/unified/quotes` and `stock_brokers/instruments/ticks/fyers.py`
leave Fyers currency derivatives out until that scaling is confirmed on a live currency pair.

**Tick sizes of uncategorised rows are not in one unit.** The uncategorised catch-alls mix paise, rupees
and Stoxkart's ten-million scaling within a single broker, so one conversion per segment would be wrong
for some rows. They are left as sent, and the order price check does not check an uncategorised
instrument's price. A few tradeable instruments also disagree by a factor other than 100 (about 25 of
300,000 on 2026-09-13, mostly Stoxkart equities at 20 or 500 times Zerodha's), which looks like stale
broker files rather than a unit problem. Index ticks were brought into rupees on 2026-09-14, as the
[mapping guide](../guides/instrument-mapping.md) describes, but Dhan's and Fyers' figures still disagree
for a few indices, such as INDIA VIX (0.05 and 0.01), and `/details` answers a null `tick_size` for them.

**Orders are refused between midnight and the morning cache warm.** `POST /api/orders/place` reads the
instrument, its broker tokens and its lots and ticks only from the `unified:catalogue:` keys in Redis, so
that it never waits on PostgreSQL. Those keys expire at midnight, and the next warm runs after the 07:45
instrument mapping, so an after-market order sent in between is refused with `404`. Running
`python -m stock_brokers.instruments.mapping.utilities.warm_cache` refills them for the latest mapping date.

**Placing an order is confirmed live at every broker except Stoxkart.** On 2026-09-15 one-share NSE CNC
limit buys were sent through `POST /api/orders/place`, and Dhan, Flattrade, Fyers, Groww, INDmoney, Kotak,
Shoonya, Wisdom Capital and Zerodha each accepted and filled theirs. Stoxkart could not log in that
morning, so it was skipped.

**Stoxkart refuses every order with `invalid algo_id`.** Later on 2026-09-15 two live test orders for one
KWIL share, an NSE `DELIVERY` `LIMIT` buy at 39.00 against a last price of 41.18, were refused by Stoxkart
with HTTP 400 and `{"message":"invalid algo_id","status":"failed","code":"ValidationError"}`. The first
carried no `algo_id` and the second carried `"algo_id": "0"`, which is what `POST /api/orders/place` sends.
No order reached the exchange. The correct algo identifier is not known. The variable
`UNIFIED_BROKER_INTERFACE_API_ORDER_EXCLUDED_BROKERS` was not set on 2026-09-15, so an order the rotation
sends to Stoxkart is refused; setting it to `stoxkart` passes Stoxkart over until the identifier is found.

**Kotak refuses every order from an IP address it has not whitelisted.** Kotak first answered
`{"stCode": 100008, "errMsg": "unauthorized", "stat": "Not_Ok"}`. The removed order code read this as a
read-only API app, but Kotak's
[static IP page](https://www.kotakneo.com/platform/kotak-neo-trade-api/static-ip-details/) documents
`100008` as the answer to a place, modify or cancel request from an IP address that is not whitelisted.
Since 1 April 2026 Kotak accepts order requests only from the account's registered static IPs, at most two,
changeable once every seven days under More → Trade API in the Kotak Neo app, and only on a session created
from the same IP, which is otherwise refused with `stCode` `1037`. Reads carry no IP check, which is why the
order book, positions and funds scripts kept working while writes were refused. Once the host's public IPv4
address was registered, the next order was accepted with no code change and no new login. If the host's
public address changes, Kotak orders fail again with `100008` until the new address is registered.

**Cancelling an order is unconfirmed live, and misses some orders.** `DELETE /api/orders/cancel` finds an
order's broker in the `<broker>:orders:orders` hashes, so it cannot cancel an order that no order script has
recorded yet. A Stoxkart order is recorded only by `bin/stoxkart/orders`, which polls once a second, and no
Stoxkart order has existed to cancel, so Stoxkart's cancel, which lowercases the order book's `NORMAL`
variety into the URL, is untried. Each broker's cancel
request is copied from the `build_cancel` methods removed in commit 4cc8c91 and was checked only against
stubbed answers. Kotak's request always sends `am` as `NO`, as the removed code did, so a Kotak after-market
order may be refused. INDmoney's fallback segment, used when the stored order names none, assumes derivative
order ids start with `DRV`, which has not been seen on a live order.

**Most unified tick normalizers are unconfirmed live.** Only Zerodha is verified, and Dhan agrees with it
on stored in-session MCX ticks but has no in-session NSE ticks stored. Kotak agreed with it on every field
in a live NSE and MCX session on 2026-09-15, INDmoney on NSE the same day, and Stoxkart's polled quotes on
close, NSE volume, MCX lots and last trade time the same day, but none of the three is yet marked verified. What Flattrade, Shoonya, Wisdom Capital, Fyers and Groww send was taken from stored weekend snapshots, a mock session
or the protocol, and the table in
[Unified scripts](../guides/unified-scripts.md#what-each-brokers-values-mean) marks which.

## Broker limits

**Flattrade permits one websocket per session.** Its market and order sockets each kicked the
other off on connect, both flapping in lockstep at close code 1000, while Shoonya runs both
happily on the same platform. `flattrade@order_updates` is left out of `flattrade.target` so
`flattrade@quotes` holds the connection, which makes Flattrade the one gap in the live half of the system. Noren can carry
order updates on the market socket, and that is the way to get both back.

**Stoxkart has no order feed.** Stoxkart delivers order status only to a Postback URL registered on the
API app, which needs a public web server that this project does not run. There is therefore no
`bin/stoxkart/order_updates` or `persist_orders`, Stoxkart is not in `bin/unified/order_updates`, and its
orders reach `stoxkart:orders:orders` only through the one-second `orders` poller.

**Stoxkart's quote websocket cannot be reached, so its quotes are polled.** The documented binary feed at
`ws://inmob.stoxkart.com:7763` refused connections on 2026-09-15, and port 443 on the same host answered
HTTP 503 from an empty AWS load balancer. `bin/stoxkart/quotes` polls `POST /quotes` once a second instead,
so a Stoxkart tick arrives up to a second after the trade, and `bin/unified/quotes` ranks Stoxkart last.
`BSECD` and `NCDEX` instruments were refused as invalid by `/quotes` the same day, although Stoxkart lists
both exchanges.

**Stoxkart's order, trade and position fields are unconfirmed.** No order, fill or open position has
existed on the Stoxkart account, so `bin/stoxkart/orders`, `trades` and `positions`, and the unified readers
of them, use the field names in Stoxkart's documentation. The holdings row seen live already differed from
that documentation, carrying `nse_symbol`, `nse_token`, `bse_symbol`, `bse_token` and `isin_code` in place
of a single `symbol` and `token`, so the other books may differ too. The sign of `net_quantity` for a short
position is also unverified.

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
