# Notes on `utilities/configurations.py`

## Why `book_configuration` can only slow the pollers down

Each per-broker order-book and trade-book poller downloads the broker's whole book for the day on every pass, and that grows with every order placed. With the order engine placing many orders, and every broker's order websocket carrying the live state, the books can be polled less often, as a reconciliation behind the websockets rather than the main source. `UNIFIED_BROKER_INTERFACE_BOOK_POLL_SECONDS` sets that, and each poller takes the larger of it and its own interval, because some intervals are what a broker allows (Fyers' five and fifteen seconds after it blocked faster polling), and a setting meant to slow things down must never speed one of those up. Unset, it is zero, and nothing changes; the plan's five-second default was not applied, because slowing the pollers is only safe where the websocket scripts are known to be running, which is an operational decision.

The pollers read it inside `main`, after importing this module, because `.env` is loaded by that import; Stoxkart's two pollers import this module at the top and read it there.

## `order_plan_types` (2026-10-02)

Read like `order_excluded_brokers`: spaces removed, lower-cased and split on commas, so an empty variable gives `['']`, which `PlanRouting` skips. It names the fixed synthetic types the engine runs as plans during the switch-over; see the note on `plan_routing.py`.
