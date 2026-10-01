# Notes on `unified_broker_interface/utilities/order_engine/utilities/preset_expander.py`

## Why a preset expands into slot values written as a caller would write them

Expanding into the same JSON a caller writes by hand means the plan reader checks presets and hand-written values with one set of rules and one set of messages. A problem in a preset's value is reported under the preset's path, so the caller sees which preset it came from.

## Why each preset keeps its type's setting names

A caller moving from `{"type": "market_if_touched", "trigger_price": 995}` to a plan writes `{"market_if_touched": {"trigger_price": 995}}` and nothing else changes. That is what lets the switch-over stage route an old type name to its preset without callers noticing.

## Why the hidden stop's backstop is refused for now

The backstop is a second order resting beside the engine-side stop, cancelled before the exit is sent. That needs the Either join with `cancel_before_send`, which is step 2b, so `backstop_price` is reported as a setting the preset does not take yet.

## Stage 2b: presets that stand for joins

`expand_join` returns a whole plan tree written as a caller would write it. Bracket and cover set `cancel_first_on_child_fill`, OCO is an Either that reduces with no main order, OTO maps its `then` body onto a child order's side and pricing (only `transaction_type`, `order_type`, `price` and `trigger_price` so far; other body fields are refused as `not_built`), and a hidden stop with a backstop is an Either that cancels, with `cancel_before_send`. The hidden stop's backstop was refused as an unknown setting in stage 2a and is now how the join is recognised.

## Stage 2c: trailing presets

`trailing_stop` is the `protect` side with `trail` pricing, and `trailing_entry` is `trail` pricing on the body's side, matching `TrailingStop` and `TrailingEntry`, which differ only in which side the stop is on. `activate_at` becomes a `price_crosses` trigger. For a trailing entry the default direction is the right one; for a trailing stop it is the opposite (a long's stop activates when the price rises to the level), so the expander needs the opening side, and reports `needs_side` when it was not given.

## Stage 4a (2026-10-01)

`peg` and `chaser` keep their types' setting names, and `cap_price` becomes a `cap` modifier beside the pricing. `post_only` stands for the guard alone, so the order's price is the body's or a `fixed` pricing the caller adds.

## Stage 4b (2026-10-01)

`underlying_peg` and `volatility` keep their types' names, `watch_instrument_id`, `lowest_price` and `highest_price`, and map them to the pricing's `instrument_id`, `lowest` and `highest`. `discretionary` maps `discretion_points` and `discretion_quantity` to the modifier's `points` and `quantity`.
