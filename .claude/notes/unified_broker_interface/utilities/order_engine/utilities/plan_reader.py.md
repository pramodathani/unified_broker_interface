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

## Stage 4a (2026-10-01)

A pricing list now holds at most one setter and at most one `cap`, and across presets a later setter or cap replaces an earlier one with a warning, so the `peg` preset's cap survives a caller's own `fixed` price. The `guards` slot reads `post_only`. Two combinations are refused rather than run: `post_only_crosses`, a post-only guard with a pricing that means to trade at once (`marketable`, `chase`, a peg to the opposite touch, a `MARKET` order), and `post_only_needs_limit`, a post-only guard on a stop. The `stop_not_sliced` rule now names the stop pricings themselves rather than every pricing that moves, because a peg or a chase on each slice is a sensible thing to want. `_refuse_unknown` takes a `kind`, so an execution's or a guard's unknown setting is no longer called a pricing.

## Stage 4b (2026-10-01)

`follow_instrument` and `option_model` are setters and `discretion` a second modifier. Discretion is refused on a stop and with any execution other than `all_at_once`. Whether the followed instrument is the order's own, and whether an option is an option, need the body and the catalogue, so they are checked by the pricing when the plan is placed rather than here.

## Stage 4c (2026-10-01)

`STOP_PRICINGS` lists every pricing that rests a stop, so the rules that refuse a stop with slicing, post-only or discretion name them in one place. `trail` takes `atr`, and `stages` reads today's stepped stop's rules, refusing them with a path to the rule rather than a rule number.

## Stage 4d (2026-10-01)

The `lifetime` slot is a list holding one object, with the end and its settings in the same object rather than under a name as the other slots are, because a lifetime is one value with options rather than a choice between named kinds. `close_filled` is refused for any order but the root, and for a protecting order; `marketable` is refused for a stop. `after_days` and `when` are recognised and refused as not built.

## Stage 5a (2026-10-01)

`together` and `sequence` are built. An order may give `instrument_id`, `quantity`, `transaction_type`, `product`, `validity` and `tag` of its own, checked by `_read_overrides`. A together or sequence join cannot be a Then join's child, because Then sizes its child to fills and these joins' children trade their own quantities (`join_not_sized`). A join holds at most 25 children, today's basket limit.

## Stage 5b (2026-10-01)

`close` is a side and `quantity` may be `{"position": {...}}`, which presets can supply as a slot; a later source's position replaces an earlier one. The two must come together (`close_needs_position`, `position_needs_close`), and a close refuses pricing and execution of its own (`close_prices_itself`).

## Stage 5c (2026-10-01)

`repeat` is read into `times` copies of its order with `ElapsedCondition` triggers; its child must be an order node (`repeat_needs_order`), because copies are given triggers. `every_trading_day_at` and `until` are recognised and refused as not built. A repeat cannot be a Then join's child.

## Stage 5d (2026-10-01)

`quantity` may be `{"parent_fill": {...}}`; `top_up` is an execution and `from_parent_fill` a pricing. Both kinds of fill-following need the order to be a Then join's child, which `_read_then` marks and `_check_fill_sizing` checks once the whole tree is read; `from_parent_fill` also needs the first plan to be a single order, whose path it is given.

## Stage 5f (2026-10-01)

`candle_closes` is a trigger condition with `level`, `direction` and `bar_minutes`.

## The `venue` slot (2026-10-01)

A venue turns into a `time_from` trigger at its `at_time`, so the order waits in the ordinary way and recovery needs nothing new. An order with a trigger of its own is refused as `pre_open_sets_its_time`, because two times would leave it unclear when the order goes, and a price trigger could send it after collection closed.

## The `paper` venue and `limit_marketable` (2026-10-01)

`paper` takes no `at_time` and adds no trigger. The reader insists on a `limit_marketable` trigger alone and on the order being the whole plan; the reasons are in the paper venue's note. Any order whose trigger includes `limit_marketable` must keep the body's own pricing.

## Kept-whole presets (2026-10-02)

A kept-whole preset expands to a `whole` slot naming its type and settings. The reader builds that type's part from `WHOLE_PART_CLASSES` and refuses it beside another preset or any slot value as `kept_whole_alone`, as the design's table of refused combinations asks. The order's plain overrides, such as its instrument and quantity, still apply, since they only change the body the part reads.

## Every join built (2026-10-02)

With `using` read by `_read_using`, every join the design names is built, so the branch that answered `join_not_built` could no longer be reached and was removed with `BUILT_JOIN_NAMES`. The execution list now reads one value or two nested ones through `_read_execution_value`.

## from_fill (2026-10-02)

`from_fill` is read by `_read_from_fill`: exactly one of a stop (`stop_distance` with `stop_limit_offset`) or a target (`target_distance`). The Then join copies its `opened_by` list into the pricing, and a `from_fill` part with no `opened_by` is refused as `from_fill_needs_then`. Its stop variant joins `STOP_PRICINGS` in the `stop_not_sliced` rule.

## `periods` is at most 49 (2026-10-04)

`BarBuilder` keeps `MOST_KEPT_BARS` (50) closed bars, and an average true range over `periods` needs `periods + 1` of them, the extra one for the first true range's previous close. With no upper bound, `periods` of 50 or more was accepted and never produced an average, so the trail stayed at `trail_points` for the whole day. The bound is taken from `MOST_KEPT_BARS` so the two cannot drift apart.

## Market and stop bodies (2026-10-05)

`_fixed_order_type` reads the order type a fixed pricing really sends, the body's when the pricing names none. `_can_rest` and `_can_take_at_discretion` only looked at the pricing, so a routed `post_only` with a `MARKET` body was sent as `MKT`, a post-only `SL` with `rest` became a buy stop whose limit sat below its own trigger, and a discretionary stop was cancelled by its first take.

## Held pieces need a holdable body (2026-10-05)

`_held_pieces_tree` turned any twap or front_loaded order into held virtual-limit pieces when holding was on, without the body checks `_why_not_held` makes. A MARKET or stop TWAP was refused with 'a virtual limit order is held at its own limit price', and an IOC TWAP was held. `_body_cannot_be_held` now makes those checks, and such an order is read as it stands and sent unheld.

## The second leg knows its own path (2026-10-05)

The Then join reading sets `own_path` on a `from_parent_fill` pricing beside `first_path`, so the pricing can count the second leg's earlier orders when it prices the next one.
