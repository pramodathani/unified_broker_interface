# Notes on `unified_broker_interface/utilities/order_engine/utilities/candle_closes_condition.py`

## Why it copies the candle close stop's rules

Bars of `bar_minutes` built from the last traded price with `BarBuilder`, an answer only when a bar closes, and the hidden stop's default direction are the rules of `candle_close_stop.py`. The offline scenarios `a_plan_candle_close_stop_*` send the same requests as today's. Today's type watches the last price for its bars while its plain hidden stop watches the opposite touch; this condition uses the last price, as the candle close stop does.

## The bars across a restart

The bars live in the trigger's memory, which is saved with the parent on every tick but recorded with an event only when the order fires, so a restart can lose a bar in progress, as today's type loses whatever was saved without an event. The next bar is built afresh, which can delay an exit by one bar, never fire one early.

## `closing_past` (2026-10-04)

A candle stop judges only the bar in progress, so closed bars do not help it after a restart; what it loses is whether the bar in progress is closing beyond the level. `closing_past` is that verdict at the latest price, and the plan writes an event when it changes, a few times a day rather than every second. After a restart late in a bar the stored close is on the same side as the true one, so the bar is judged the same way (`a_candle_close_stop_remembers_which_side_its_bar_is_closing_on_across_a_restart`).

The docstring said nothing is known until the first bar after the order rests has closed. The bar the order is placed in is tested too, at the next clock boundary.

## Stale quotes (2026-10-05)

A quote marked `stale` used to be read like any other, so with holding off a stale touch fired a `limit_if_touched` and sent its limit at once (found in the group 3 walkthrough). The quote combiner marks a quote stale when its broker has gone silent and no healthy backup exists, so the price may be minutes old. `LimitMarketableCondition` already ignored such quotes; this condition now does the same, returning False before its memory is touched, so a stale tick neither fires nor counts towards, nor resets, a confirmation. A time-based age limit was not added, because staleness is already decided from broker health in one place.
