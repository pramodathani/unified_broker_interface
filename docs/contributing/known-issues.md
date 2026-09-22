# Known issues

Things that are wrong, unfinished or deliberately left alone, recorded so they are not
rediscovered from scratch. Everything here was checked against the code on 2026-09-19.

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
for some rows. They are left as sent, and `POST /api/orders/place` refuses an uncategorised instrument with
`400` before any price check. A few tradeable instruments also disagree by a factor other than 100 (about 25 of
300,000 on 2026-09-13, mostly Stoxkart equities at 20 or 500 times Zerodha's), which looks like stale
broker files rather than a unit problem. Index ticks were brought into rupees on 2026-09-14, as the
[mapping guide](../guides/instrument-mapping.md) describes, but Dhan's and Fyers' figures still disagree
for a few indices, such as INDIA VIX (0.05 and 0.01), and `/details` answers a null `tick_size` for them.

**Orders are refused between midnight and the morning cache warm.** `POST /api/orders/place` reads the
instrument, its broker tokens and its lots and ticks only from the `unified:catalogue:` keys in Redis, or
from the API worker's own copy of them, so that it never waits on PostgreSQL. Those keys expire at midnight,
the worker's copy is dropped at the same moment, and the next warm runs after the 07:45
instrument mapping, so an after-market order sent in between is refused with `404`. Running
`python -m stock_brokers.instruments.mapping.utilities.warm_cache` refills them for the latest mapping date.

**The order connections' idle limits come from one measurement.** Each broker's `MAXIMUM_IDLE_SECONDS` in
`unified_broker_interface/utilities/broker_orders/` is set below the idle timeout its server showed on
2026-09-15, measured once from this host: 65 seconds at Shoonya and Wisdom Capital, 240 at Dhan, 400 at the
Cloudflare-fronted Zerodha, Fyers, Groww, INDmoney and Flattrade, 600 at Kotak's `e43` host and more than 600
at Stoxkart. A broker that later shortens its timeout below the limit brings back the failure the limit
prevents: an order sent on a connection the server has already closed is answered `unknown`. Warming pings
also reach Cloudflare's bot protection at four of those hosts, which set a cookie on a plain `HEAD /`, and
INDmoney answers it `403`; no block has been seen, but a broker's firewall reacting to the pings is why warming
is off unless `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS` names the broker.

**Currency and commodity markets were opened before live orders confirmed them.** On 2026-09-15 the user asked
for every segment to be ready for orders that evening, and each broker's `MARKETS` and `QUANTITY_UNITS` were given
every currency and commodity market its documentation supports, all counting quantity as lots times the broker's
own lot size. That rule comes from Zerodha's and Dhan's staff answers, from Shoonya's documented rule for
derivatives, from XTS documentation whose own examples contradict it, and by inference elsewhere; Fyers is unknown.
Groww's commodity markets were listed too and were removed the same evening, after a live order showed Groww's API
takes no commodity orders. Zerodha's `NCO` and `BCD`, Wisdom Capital's `NSECO` and Stoxkart's `BSECD` and `NCDEX`
codes are not confirmed either. A wrong code is refused by the broker; a wrong quantity rule is not. Live orders are
tested on MCX CRUDEOILM, whose lot is 1 at Zerodha, Dhan, Fyers and Wisdom Capital and 10 at Kotak, Shoonya,
Flattrade and Stoxkart, with a limit buy about 2% below the market. On 2026-09-15 at about 21:30, with CRUDEOILM's
21 September future at 10,043, one lot was sent at 9,842:

| Broker | Sent | Answer | What it shows |
| --- | --- | --- | --- |
| Zerodha | quantity 1 on `MCX`, NRML | HTTP 422 `InputException`: "MCX is disabled for your account", with a link to activate the segment in Console; nothing was placed | The request is accepted up to the account check; the quantity rule is still unconfirmed |
| Dhan | quantity 1 on `MCX_COMM`, `MARGIN` | Accepted as order 23826091527008 (`TRANSIT`) in 72 ms, then `REJECTED` by Dhan's risk system: "You have insufficient funds. Please add Rs.25406.10 to trade." | Dhan recorded quantity 1. A shortfall of about Rs 25,400 fits the margin of one lot (about Rs 98,000 of oil) rather than ten, but the account's balance was not known, so this supports the rule without proving it |

At about 21:50 the same evening one lot of GOLDPETAL's 30 September future, whose lot is one gram at Groww and in
the morning's contract size decision, was sent to Groww as quantity 1 on segment `COMMODITY`, a limit buy at 14,820
with the market at 15,124. Groww answered HTTP 422 with `GA001` "Orders are currently not supported for commodity
segment." in 85 ms, and `groww:orders:orders` gained no entry, so Groww created no order. Groww's order documentation
lists only `CASH` and `FNO` for placing, listing and cancelling orders, so its `MARKETS` no longer lists MCX or NSE
commodities, and a commodity order now passes Groww over instead of being refused there.

No order reached the exchange. The other six brokers were not tested that evening. An insufficient-funds rejection
names the margin wanted, which says whether a broker read the quantity as one lot or as ten, so an unfunded account
can still be used to test the rule.

**BSE currencies and NCDEX trust Stoxkart's lot size alone.** No other broker's instrument file lists them, and on
2026-09-15 the user chose to trade them on Stoxkart's figure rather than keep them closed. Stoxkart's NCDEX lot sizes
(JEERAUNJHA 3, GUARSEED10 5) are in the exchange's trading unit, tonnes, not the quotation unit, quintals: NCDEX's
specifications give JEERAUNJHA a 3 MT unit priced per quintal and GUARSEED10 a 5 MT unit priced per quintal (from its
2019 and 2020 circulars and 2023 one-pagers; the 2026 pages could not be loaded). An NCDEX `quantity` is therefore in
tonnes, and a caller sending quintals would be read as ten times too many lots. Stoxkart's order documentation does
not list NCDEX or BSECD at all.

**Some contract sizes are conflicts every day.** On 2026-09-15 Kotak gave the 12 NSE SILVER100 futures a contract
size of 100 where Wisdom Capital and Groww gave 1, and Stoxkart gave 9 NSE GBPINR and JPYINR options 2000 where Kotak
and Shoonya gave 1000. Those contracts are refused until the sources agree.

**Flattrade rounds currency option strikes, which splits some contracts in two.** Flattrade lists NSE USDINR strikes
to two decimals (95.88 for the exchange's 95.875), so the mapping computes a different `instrument_id` from the
other brokers' and 302 NSE currency options on 2026-09-15 were carried by Flattrade alone. They have no contract size
source and are refused.

**Placing an order is confirmed live at every broker, but no Stoxkart order has filled yet.** On
2026-09-15 one-share NSE CNC limit buys were sent through `POST /api/orders/place`, and Dhan, Flattrade,
Fyers, Groww, INDmoney, Kotak, Shoonya, Wisdom Capital and Zerodha each accepted and filled theirs.
Stoxkart could not log in that morning, so it was skipped. Later that day Stoxkart refused orders with
`invalid algo_id` until the Algo-ID was sent as an `X-Algo-Id` header, as
[Pitfalls](pitfalls.md#placing-and-cancelling-orders) describes. With the header, three NSE KWIL orders
sent at 15:40 IST passed the Algo-ID check and were rejected by Stoxkart's risk checks only because the
market had closed, with `MARKET IS CLOSE YOU CANNOT PLACE AN ORDER NOW`. Two after-market orders for one
KWIL share, one on NSE and one on BSE, were then sent to Stoxkart's `POST /orders/amo` with the header and
accepted with HTTP 200, `Order Submitted` and status `AMO PENDING`. Stoxkart therefore takes orders, but
no Stoxkart order has yet been placed during market hours or filled at the exchange.

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

**Cancelling an order is confirmed live at seven brokers, and misses some orders.** `DELETE /api/orders/cancel` finds an
order's broker in the `<broker>:orders:orders` hashes, so it cannot cancel an order that no order script has
recorded yet. A Stoxkart order is recorded by `bin/stoxkart/orders`, which polls once a second, or by
`bin/stoxkart/order_updates` from Stoxkart's order socket. On 2026-09-15 cancels of after-market orders were
accepted and ended cancelled with nothing traded at Dhan, Flattrade, INDmoney, Kotak, Shoonya, Stoxkart and
Zerodha, as the live test below describes. No cancel of an open order during market hours has been tried, and
Fyers', Groww's and Wisdom Capital's cancels are checked only against stubbed answers. Kotak refused the first
cancel of an after-market order, sent with `am` of `NO` as the removed code did, with `error from core` and
`hash error`; the cancel now sends `YES` when Kotak's order book marks the order `ordGenTp` `AMO`, and that was
accepted. INDmoney's fallback segment, used when the stored order names none, assumes derivative order ids start
with `DRV`, which has not been seen on a live order.

**Modifying an order is confirmed live at six brokers, only on after-market orders.** `PUT /api/orders/modify` was
added on 2026-09-15. Each broker's request is built from that broker's current documentation, its official SDK and,
for Kotak, which publishes no raw REST documentation, from Kotak's SDK and one production library.

Between 22:48 and 23:05 IST that day the branch's routes were run in-process against the live Redis, one broker at a
time with every other broker excluded, with the user's permission. At each broker they placed an after-market NSE buy
of one KWIL share at ₹33, changed its price and then its quantity to 2, and cancelled it. KWIL was trading near ₹41,
so nothing filled, and every test order ended cancelled.

| Broker | Place | Modify price | Modify quantity | Cancel |
| --- | --- | --- | --- | --- |
| Flattrade | accepted | accepted | accepted | accepted |
| INDmoney | accepted | accepted, after a fix | accepted, after a fix | accepted |
| Kotak | accepted | accepted | accepted | accepted, after a fix |
| Shoonya | accepted | accepted | accepted, after a fix | accepted |
| Stoxkart | accepted | accepted | accepted | accepted |
| Zerodha | accepted | accepted at ₹33.50; ₹32.50 was refused as below the lower circuit limit of ₹32.67 | accepted | accepted |
| Dhan | accepted | refused: `DH-906` `Market is Closed! You cannot modify/cancel an order now.` | refused, the same | accepted |
| Fyers | refused: `AMO order placement is not supported via API.` | not tried | not tried | not tried |
| Groww, Wisdom Capital | not sent: their order classes take no after-market orders | not tried | not tried | not tried |

Each change showed in the broker's order book in Redis within a second, and the route found the order's instrument
from its stored token at every broker it tried. Three fixes came out of the test. INDmoney's order book stores no
validity, and a Shoonya websocket update carried no product, so a modification now treats a missing side, product
or validity as a gap only at the brokers whose modify request sends it. Kotak's cancel now reads the after-market
flag, as above.

Dhan's refusal came from its order checks, not from a malformed request, so its modify request needs a test during
market hours; so do Fyers', Groww's and Wisdom Capital's. Several things are still open:

| Broker | Not yet confirmed |
| --- | --- |
| Zerodha | Which variety an after-market order's modification needs once the market opens, when Kite treats it as a regular order; and a live SL-M order with `market_protection=-1`, since only a MARKET order has been placed with it |
| Dhan | The whole modify request, which was refused after hours; whether `legName`, which Dhan documents only for bracket and cover orders, is needed on a regular order; and whether `STOP_LOSS_MARKET` is honoured |
| Fyers, Groww, Wisdom Capital | The whole modify request |
| Fyers, Groww, INDmoney, Stoxkart, Wisdom Capital | Whether the quantity is the new total quantity or the pending quantity after a partial fill; Zerodha, Dhan and Noren document the total, and no test order filled |
| Every broker | How a modification behaves on an order during market hours, and on stop-loss and market orders |
| Stoxkart | Whether a modification needs the `X-Algo-Id` header, which was sent in the live test because placements need it |

The modification finds the order's instrument from the broker token stored on the order, and treats the token as
text that must equal the token in `unified:catalogue:<date>:tokens:<broker>`. The stored tokens matched at every broker
the test reached. At Stoxkart, BSE KWIL's token `544622` also names an MCX commodity option, which the exchange check
tells apart. Groww stores no token on its orders, so a Groww modification is never checked against the tick size.

**Most unified tick normalizers are unconfirmed live.** Only Zerodha is verified, and Dhan agrees with it
on stored in-session MCX ticks but has no in-session NSE ticks stored. Kotak agreed with it on every field
in a live NSE and MCX session on 2026-09-15, INDmoney on NSE the same day, and Stoxkart's streamed ticks on
price, volume, average price, OHLC, previous close, total bid and offered quantity, first depth level, MCX
lots and both times the same day, but none of the three is yet marked verified. What Flattrade, Shoonya, Wisdom Capital, Fyers and Groww send was taken from stored weekend snapshots, a mock session
or the protocol, and the table in
[Unified scripts](../guides/unified-scripts.md#what-each-brokers-values-mean) marks which.

## Broker limits

**Zerodha's quote feed runs past Kite's documented websocket limits, and has not been tried live.** On
2026-09-16 `bin/zerodha/quotes` was changed to subscribe to every instrument in today's
`zerodha:instruments:master` - 112,657 that day - split equally across 24 websockets, one part of 4,695 and
twenty-three of 4,694. Kite documents three websockets per api key, one of which `bin/zerodha/order_updates`
holds, and 3,000 instruments per websocket, so this exceeds both, and the connection budget and the
per-connection cap that used to refuse it were removed. What Kite does with the connections past its limit is
unknown: it is expected to refuse them, and a refused socket reconnects with backoff and leaves the others
streaming, but no run against the live feed has confirmed that. Two further consequences are expected rather
than measured. Full-mode ticks for 112,657 instruments outrun `zerodha:quotes:stream`, whose cap was raised
from 100,000 entries to 1,000,000 the same day for that reason, so `bin/zerodha/persist_ticks` still has to
keep up or Redis will trim ticks before it has persisted them into `zerodha.ticks`. Every login also
invalidates the last at Zerodha, so 24 sockets reconnecting after a dead token lean much harder on the
one-socket-at-a-time login lock than two ever did.

**The unified quote layer has never been run at the size Zerodha's feed now gives it.** `bin/unified/quotes`
keeps no instrument list of its own - it writes a unified quote for every tick that arrives on the ten broker
streams - so Zerodha's 24-socket feed raises its coverage from sixteen instruments to about 112,400 without
any change to it. Nothing about that is configured, and nothing about it has been measured either. It is one
process reading all ten streams 500 entries at a time; its hourly stale purge reads and JSON-parses every
field of `unified:quotes:live`, now about 112,400 documents, on the same thread that processes ticks; and its
start-up recovery of today's previous closes does the same scan once. `unified:quotes:stream` was raised from
200,000 entries to 1,000,000 alongside the broker streams, which at a measured 823 bytes per quote document is
about 820 MB, and `unified:quotes:live` itself comes to roughly 92 MB. Watch `unified:quotes:stats` and the
`unified` consumer group's lag on `zerodha:quotes:stream` the first time this runs during market hours.

**Every broker's tick stream now holds ten times as much.** On 2026-09-16 `STREAM_MAX_LENGTH` in all ten
`bin/<broker>/quotes` scripts went from 100,000 to 1,000,000 entries. The stored ticks were measured that day:
a Zerodha tick averages 940 bytes of JSON and the ten brokers range from 504 bytes at Fyers to 1,071 at Groww,
so Zerodha's stream at the new cap is about 940 MB of payload and all ten brokers' streams full at once come
to about 7.8 GB, before Redis's own stream overhead. That host has 123 GB of memory, was using 3 GB, and has `maxmemory` unset with
`noeviction`, so there is room, but nothing now bounds Redis below the machine's memory. Only Zerodha
subscribes to enough instruments to approach the cap: the other nine carry between five and fifteen
instruments each and will never come near it.

**Flattrade permits one websocket per session.** Its market and order sockets each kicked the
other off on connect, both flapping in lockstep at close code 1000, while Shoonya runs both
happily on the same platform. `flattrade@order_updates` is left out of `flattrade.target` so
`flattrade@quotes` holds the connection, which makes Flattrade the one gap in the live half of the system. Noren can carry
order updates on the market socket, and that is the way to get both back.

**Stoxkart's feeds are its trading website's, not documented API feeds.** The documented binary quote
websocket at `ws://inmob.stoxkart.com:7763` could not be reached on 2026-09-15, and the documented order
status needs a Postback URL on a public web server that this project does not run. `bin/stoxkart/quotes`
and `bin/stoxkart/order_updates` therefore use the two websockets Stoxkart's own trading website uses,
`wss://broadcasting-v2.stoxkart.com/` and `wss://openapi-v2.stoxkart.com/websocket/v2/connect`. Neither is
documented for API users, so Stoxkart may change either without notice. The REST quote poller the quote
feed replaced is in git history as a fallback. `bin/unified/quotes` ranks Stoxkart last.

**Stoxkart's quote feed covers four exchanges.** `bin/stoxkart/quotes` accepts NSE, NFO, BSE and MCX
instruments and refuses `NSECD`, `BSECD`, `BFO` and `NCDEX`, because no trade packet was seen for them on
2026-09-15 and their broadcast segment numbers are unconfirmed.

**Stoxkart allows one order socket per client.** A new connection closes the older one with a close reason
containing `new incoming connection`, so `stoxkart@order_updates` and a Stoxkart website or app logged in to
the same account knock each other off. The script waits five minutes before reclaiming the socket, and
order updates are missed while the website or app holds it; the `orders` poller still records the orders.

**Stoxkart refuses logins from 23:40 to midnight, and the pollers crash-loop through it.** On 2026-09-18 and
2026-09-19, Stoxkart ended the session at exactly 23:40:00, and every login until just after 00:00 was refused
in `_exchange_request_token` with `('AuthorizationError', 'Session is expired')`, the same message as the
expired session itself. The six REST pollers (`orders`, `trades`, `positions`, `holdings`, `funds` and
`user-profile`) build `StoxkartAPI` when their session is refused, the login raises, the script exits 1, and
systemd restarts it 15 seconds later. Each poller therefore fails about 70 times in those 20 minutes, which is
roughly 420 refused logins a night across the six, each with a full traceback in the journal. On 2026-09-20 the
first login that worked was at 00:00:03, and every poller ran cleanly from then on. No data is lost, because MCX
closes at 23:30 and nothing trades in the window, but so many refused logins could lead Stoxkart to rate-limit
or lock the account. A poller that waited a few minutes after a refused login instead of exiting would avoid
this. The four other Stoxkart scripts, `quotes`, `order_updates`, `persist_orders` and `persist_ticks`, are
unaffected.

**Stoxkart's servers fail briefly in the early morning.** Around 05:30 and 06:20 on 2026-09-18 and 2026-09-19,
Stoxkart's login answered `('E-999', 'Stoxkart rejected /auth/v2/login with HTTP 500: System error')` or
`('GeneralError', 'Something went wrong')`, and polls to `openapi.stoxkart.com` timed out after 10 seconds.
Each episode lasted a few minutes, restarted the pollers a handful of times, and cleared on its own well
before the 09:00 pre-open.

**Stoxkart's trade and position fields, and its open and filled orders, are unconfirmed.** No fill or
open position has existed on the Stoxkart account, so `bin/stoxkart/trades` and `positions`, and the
unified readers of them, use the field names in Stoxkart's documentation. The order book and the order
socket were seen live on 2026-09-15, but only for rejected, after-market and cancelled orders, whose
statuses were `REJECTED`, `AMO PENDING` (normalized to `PENDING`) and `AMO CANCELLED` (normalized to
`CANCELLED`). The statuses of an open, partly filled or filled order, and the socket updates that go with
them, have not been seen. The order book's `order_date_time` looked like `15-Sep-2026 15:40:40`, and
`exch_order_id` and `parent_order_id` were `"0"` before an id was assigned, which the normalized order
holds as null while `data` keeps Stoxkart's `"0"`. `bin/stoxkart/order_updates` still logs every message at INFO so that the first update for an
open or filled order shows its shape. The holdings row seen live already differed from
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
