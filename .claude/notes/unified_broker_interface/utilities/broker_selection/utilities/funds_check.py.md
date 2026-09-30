# Notes on `unified_broker_interface/utilities/broker_selection/utilities/funds_check.py`

Written on 2026-09-30, after calling every broker's margin calculator with the same reference orders (see `.claude/notes/stock_brokers/instruments/mapping/utilities/sql/ddl/150_unified_broker_order_costs.sql.md` for the numbers).

## Why the check estimates instead of asking the broker

Nine of the ten brokers have a margin calculator, but each call is a network round trip of 75 to 100 ms (measured the same day, on fresh connections), and the user wanted the order path to stay free of extra round trips. The user also said the estimate may be cautious: passing over a broker that could have taken the order is acceptable, sending an order that will be refused is not. So the order path estimates, and the calculators are used once a day by `bin/unified/orders/margin_calibration` to measure the per-broker surcharges the estimate is multiplied by.

## Why a broker is skipped rather than ranked last

The user asked for a broker without the funds to be skipped for that order. A selector can only order brokers, so a skip needed a hook the placement asks: `BrokerSelector.passed_over_reason`, which `OrderPlacement.choose_broker` consults after the broker's own `place_skip_reason`. Its reason lands in `skipped`, which makes a refusal self-explaining. Ranking such a broker last, the way a blocked rate budget is, would still send it the order when every broker is short.

## Why the Lua script reads the mapping date itself

The selector's `queue_redis_commands` receives the order and the instrument id, not the mapping date the engine has already read. The underlying's quote needs `unified:catalogue:<date>:underlyings`, so the script reads `unified:catalogue:current_date` and builds the key inside Redis. Doing it in Lua keeps the identity, the quote and the underlying's quote to one command and no extra round trip, where plain pipelined commands would need the underlying's id before they could ask for its quote. The script touches keys it does not declare in `KEYS`; that is fine on the single Redis this project runs, and would need changing only for Redis Cluster. On 2026-09-30 it answered in 0.87 ms against live Redis for four instruments.

The script returns prices as text (`tostring`), because Redis turns a Lua number into an integer and would drop the paise.

## Why the check is thread-local

The selector is shared by the engine's threads. `queue_redis_commands`, `ranked_brokers`, `passed_over_reason` and `record_chosen` for one order all run on one thread, one after another, so the legs, reasons and requirements of the order in hand are kept on a `threading.local`, like the selector's own `queued` rows.

## What is deliberately not done

- A reservation is not released when a broker refuses the order. The answer is read on a broker lane's thread, not the one that chose the broker, so matching it to its reservation would need an identifier threaded through the send path. Instead a reservation lapses once the broker's funds are read more than `UNIFIED_BROKER_INTERFACE_API_ORDER_FUNDS_SETTLE_SECONDS` after it, which covers a refusal as well as a fill.
- Positions are not read, so an order that closes a position is still checked as if it opened one. Closing orders that name their broker (flatten, later legs) are not checked at all; a caller closing by hand through the selector may be passed over unnecessarily. Reading `unified:portfolio:positions` on the same pipeline would fix that and was left for later.
- The pool for a multi-leg order is chosen from the first leg's market, because a basket's legs are almost always in one market.
