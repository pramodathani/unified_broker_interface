# Notes on `unified_broker_interface/utilities/broker_selection/lowest_cost.py`

## Why this selector exists

The user asked on 2026-09-29 for a selector that replaces round robin as the default, minimising the brokerage paid while never running a broker out of its per-second, per-minute, per-hour or per-day order budget. They supplied a table of each broker's limits and its brokerage for delivery, F&O and intraday, and asked for every reasonable approach to be shown. Five were considered; `docs/architecture/broker-selection.md` lists them. This file is the third: cheapest first, then versatility, then paced pressure.

The user also required that no broker, fee, limit or preference be written into the code, so that a broker can be added later by adding a row to `unified.broker_order_costs`. Everything the ranking uses is computed from the table's rows at ranking time, including the versatility, which depends on the dearest fee among the brokers currently in the rotation.

## Why versatility comes before pressure

Fees are flat per order, so between two brokers with the same fee for this order nothing is saved by choosing either one now. What can be lost is a later order's saving: Flattrade is free for all three categories, so every delivery order it takes is a minute slot an F&O order could have used for free. Putting versatility ahead of pressure spends the brokers that are cheap only for this category first. Pressure then spreads orders among brokers that are equally cheap and equally versatile.

## Why a blocked broker is listed last rather than dropped

The counts can be a moment old, and the rate budget, not the selector, is what actually refuses a message. Dropping a broker could turn an order into a 503 that the rate budget would have let through after a short wait. Listing it last keeps every broker available as a fallback.

## Why the hour window is not paced

A per-day budget is a fixed allowance that resets at 06:00, so without pacing a busy morning spends it and the afternoon has nothing. The per-hour budget is a sliding window, which paces itself: messages leave it an hour after they were sent. Pacing it as well would only push orders away from Dhan in the first hour of the day for no benefit.

The per-day pacing uses the NSE equity session from `exchange_calendar.TRADING_HOURS`, because most orders are placed then. Outside the session the fraction is 0 before it and 1 after it, so evening MCX orders see the whole remaining day's allowance. Pacing only affects ties between equally cheap and versatile brokers, never whether a broker may be used, so an imprecise session length cannot refuse an order.

## Why the selector remembers its own choices

The order engine chooses the broker at intake and sends the order later, from the broker's lane. The rate budget's windows fill only when a message is sent, so a burst of a hundred orders arriving together would all read zero and all be assigned to Flattrade. Round robin avoided this because its counter moved at selection time. Writing each choice to Redis would cost a round trip per order; keeping the last hour's choices in memory costs nothing and is exact enough, because only the engine places orders. The higher of the two counts is used, so a message counted in both is not counted twice.

The deques are pruned from the left on every read, so counting a window is amortised constant time even with thousands of entries in the hour window.

## Why the counts come from one Lua script

The script reads four keys for every broker in the table, so it scales with the number of brokers and not with the orders. It uses Redis `TIME`, the clock the rate budget writes with, because the processes' own clocks can disagree by more than the one-second window. It is sent with `EVAL` rather than `EVALSHA`: a pipelined `EVALSHA` from redis-py checks `SCRIPT EXISTS` in a separate round trip before every execute, and a bare `EVALSHA` would fail after a Redis restart. `EVAL` sends about 600 bytes more per order and needs neither.

## Why the queued names are kept per thread

`queue_redis_commands` and `ranked_brokers` are called separately, and a daily reload can replace the table between them. The names and rows the script was queued for are kept on a `threading.local`, so the reply is always read against the list it was built from. A reply of the wrong length is treated as no counts rather than misread.

## Checked against the live system

On 2026-09-29 the script was run against the live Redis with a test broker whose table row allowed 5 a second: the rate budget let five messages through and made the sixth to eighth wait about a second, and the counts script returned 5 for the second, minute and hour windows. The real start-up path, `api.py`, loaded the ten rows and ranked F&O, delivery and intraday exactly as `test_runs/broker_selection.py` expects. No order was sent.
