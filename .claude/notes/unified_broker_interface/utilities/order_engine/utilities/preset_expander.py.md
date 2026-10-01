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

## Stage 4c (2026-10-01)

`_trailing_slots` holds what the trailing stop, the trailing entry and the average-range trail share, so `atr_trail` adds only its `atr` settings. `stepped_stop` does not take `trail_points`, `trail_percent` or `activate_at`, as today's type refuses them.

## Stage 4d (2026-10-01)

`good_till_time` maps `at_expiry: market` to `on_end: marketable`. `time_stop` maps `minutes` to `after_minutes`. There is no preset for the `gtt` type, because a plan does not yet outlive the trading day.

## Stage 5a (2026-10-01)

`basket` and `oca` turn each candidate into an order made of the rest of the order the preset was named in and the candidate's own values, so a basket named beside `post_only` is a basket of post-only orders. A candidate's `price` and `order_type` become `fixed` pricing, or with a `trigger_price` a `native_stop`. Today's types refuse an instrument named twice because their legs are told apart by instrument; a plan's are told apart by path, so it is allowed. Today's one-cancels-all type checks the group's margin as a basket does; the `oca` preset's Either join does not.

## Stage 5b (2026-10-01)

`close_on_trigger` and the `double` form of `stop_and_reverse` are slot values. The default `sequential` form of `stop_and_reverse` is a join, so `is_join` depends on its `method`; it is a Then join whose child, sent `on_complete` and sized to what closed, trades the side opposite to the position, which needs the body's side. `square_off` closes every instrument on its product unless `instrument_ids` narrows it, as today.

## Stage 5c (2026-10-01)

`accumulation` is a join preset: a repeat of the rest of the order, priced with a peg to the own touch that does not follow and stays within the body's limit.

## Stage 5d (2026-10-01)

`attached_hedge` chooses the hedge's side from the entry's side and the ratio's sign, as today's does, and refuses `delta_volatility` as not built. `legged_spread` takes the second candidate's side and instrument but not its quantity or price, which come from the first leg's fills.
