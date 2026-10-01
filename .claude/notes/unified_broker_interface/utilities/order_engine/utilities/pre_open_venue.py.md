# pre_open_venue.py

## Why the pre-open is a venue rather than a trigger or a pricing (2026-10-01)

The design doc lists `venue` as a slot beside pricing and execution, with `selector` as its default, because where an order is sent is independent of when and at what price. The pre-open is the first value that is not the selector's continuous market. What makes it a venue is the set of rules it brings: which segments have an auction, which order types and validities it takes, and when collection closes. Those belong to the session, not to the order's timing, so they live here and the timing is a plain `time_from` trigger the reader adds.

## Why `check` runs before the parent is recorded

`PlanOrder.run` calls `check` while it builds each part's record, before anything is written, so an order the pre-open would not take is refused with `400` and no parent, as today's type does. The check needs the instrument's segment, which the placement reads without the quantity, so it does not need to wait.

## Why a closed day passes

An order taken on a weekend or holiday is meant for the next trading day's pre-open, and the `time_from` trigger already waits for the next trading day's `at_time`. Only an order taken after collection closed on a trading day is refused, naming the next trading day, because sending it at `time_from`'s "at once" would put it into continuous trading.

## The futures cut-off

NSE closes futures collection at a random moment between 09:07 and 09:08, so 09:07 is the last safe time, the same choice today's type makes. Only current-month futures have a pre-open, and like today's type this does not check the month.
