# Notes on `unified_broker_interface/utilities/order_engine/utilities/plan_reader.py`

## Why it collects every problem

The design requires a refused plan to list every problem at once, each with the part's path and a rule name, so a caller building a large plan can fix it in one pass. The reader therefore keeps walking after a problem and returns None only at the end.

## Why the joins are listed before they exist

`JOIN_NAMES` holds the six joins of the design so a caller who writes `then` is told it is not built yet (`join_not_built`), which is true and useful, rather than that it is unknown (`unknown_node`), which would suggest a typing mistake.

## Why `PRESET_NAMES` is its own list rather than the type registry

Importing `SYNTHETIC_ORDER_CLASSES` here would be circular, because the registry imports `plan.py`, which imports this reader. It is also the wrong list: a type becomes usable as a preset only once it has been rewritten as slot values and proven live, one stage at a time.

## Stage 2a merge rules

An order's presets are expanded first and its own `trigger`, `side` and `pricing` read last, all through the same readers. Triggers from several sources become one `ConditionGroup` with `all`. A later pricing setter replaces an earlier one with a `pricing_replaced` warning rather than a refusal, as the user decided on 2026-10-01 for presets, because naming a preset for its trigger and then choosing another price is a normal thing to want. Within one hand-written `pricing` list two setters are refused, because every pricing so far sets the price from scratch. Two different sides are refused.

## Stage 2b: joins and join presets

`then` and `either` are read into `ThenPart` and `EitherPart`; the other four joins are still refused as `join_not_built`. A join preset (`bracket`, `cover`, `oco`, `oto`, and `hidden_stop` with a backstop) is found before the order is read, and the order without that preset becomes the join's main order, so `[market_if_touched, bracket]` is a bracket whose entry waits for a price. Only one join preset per order is allowed, because two would each want to be the tree around the order.

An Either's first child inherits `keeps_tag`; every other child, and every Then child, does not.
