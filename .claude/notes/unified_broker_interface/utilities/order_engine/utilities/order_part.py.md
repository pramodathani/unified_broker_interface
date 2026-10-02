# Notes on `unified_broker_interface/utilities/order_engine/utilities/order_part.py`

## Why an order part only looks at legs with its own path

Every broker order the part places carries its path as its role, and `own_legs` filters on it. This is the ownership rule the design depends on: today's types find their legs by role names such as `entry` or by counting every leg, which is what stops two types sharing a parent.

## Why the done reasons are these four

`filled`, `partly_filled`, `refused` and `cancelled` separate the outcomes a caller acts on differently. `partly_filled` ends the parent as `completed`, matching `SyntheticOrder.finish_with_legs`, which treats any traded quantity as a completed parent. A leg in `unknown` is not finished, so a part with one is not done, for the same reason `OrderLeg.is_finished` gives: treating it as done could leave a position unprotected.

## Why `expanded` writes the defaults out as words

A dry run shows the plan as it would run. With only the `simple` preset there are no slot values yet, so each slot's default is described in words, such as "the body's quantity", until later stages give the slots real values that can be written out as data.

## Stage 2a: trigger, side and pricing

The part now holds a trigger, a side and a pricing rule. It builds its order from a copy of the body: the side is set first (`protect` flips the body's side), then the pricing sets the order type and prices, and only then is `concrete_order` called, so references in the body are still resolved. `start` from stage 1 became `place`, and `PlanOrder` decides when to place; the part answers `is_triggered` and never records its own state.

## Stage 2b: parts under a join

A part now has a lifecycle a join drives: `start` with a target, `send` when a waiting part's tick comes, `settle` to mark it done, `traded`, `set_target` to resize or cancel its resting order, and `cancel_rest`. A broker order's quantity is its total, filled part included, so `set_target` changes a resting order to its filled quantity plus what is still wanted. A leg the broker has not acknowledged has no `broker_order_id` and is left alone; the next settle tries again.

`keeps_tag` is true only for the plan's main order, the root order or the first plan of a root Then join, followed down first children. Exits and children drop the caller's tag, as `ExitLegs.exit_order` and `OneTriggersOther.child_order` do today.

## Stage 2c: pricing memory and moving

A part now keeps `pricing_memory` in its record for a pricing that remembers something between ticks, and passes it to `priced_body` and `moved_prices`. `move` reprices the part's one resting order when its pricing moves.

## Why the opening side is upper-cased before it is compared

The API accepts `transaction_type` in any case and keeps the body exactly as the caller sent it; `PlaceOrderRequest` upper-cases it only when the order is validated. The plan code read the raw body, so a body with `"buy"` failed every comparison with `'BUY'`. In the live test on 2026-10-01 three IDEA plans sent with `"buy"` had their trigger treated as a sell's, waiting for the price to rise to a level it was already above, so each fired on its first tick; the one sent with `"BUY"` waited correctly. A `protect` part would have failed outright, because `OPPOSITE_SIDES['buy']` does not exist. `_opening_side` reads the side as `PlaceOrderRequest.parse_choice` does (stripped and upper-cased), and `PlanOrder._read_plan` does the same for the reader. The offline scenarios `a_plan_buy_sent_in_lower_case_still_waits_for_the_dip` and `a_plan_hidden_stop_for_a_long_sent_in_lower_case_sells` failed before the fix.

## Stage 3a: pieces

An order part now sends its quantity as pieces chosen by its execution. `send` starts it working and begins the execution's clock; `send_due` prices every due piece before sending any, so a piece that cannot be priced yet holds back the rest until the next tick; `settle` sends the next piece for an execution that waits for fills, and marks the part done only when every leg has finished and the execution will send no more. `set_target` keeps resizing the one order for `all_at_once`, and for every other execution cuts resting pieces newest first, leaving growth to later pieces.

## Stage 3b (2026-10-01)

`send` puts a part whose execution is paced by ticks into `working` even when nothing is due on the tick its trigger holds, so the execution's start (participation's `counted_volume`, a timed schedule's `started_at`) is kept and later ticks send through `send_due`. An execution that is not paced by ticks still goes back to `waiting` when its first piece cannot be priced. `send_due` passes `sending_side` to the execution and saves changed execution memory with an event once the pieces are placed.

## Stage 4a (2026-10-01)

`move` now moves every resting broker order of the part, not only the newest, so a TWAP with a peg keeps each resting slice on the bid. Each order is asked about with the memory as it stood before the tick, so pieces side by side move together. The memory is recorded with an event when an order moved or when it was first set. The cap holds every limit, sent or moved, and the post-only guard checks it; a refusal ends the part as `refused` with the guard's message, and `send` then leaves it done rather than putting it back to waiting.

## Stage 4b (2026-10-01)

Pricing memory set by `priced_body` is now recorded with an event, because the follow pricings keep their start there and a restart must not lose it. `move` gives discretion its turn before the pricing moves. `set_target` shares the wanted quantity across every resting order, oldest first with the last taking the rest, instead of giving each the whole amount, which only worked while a part had one resting order.

## Stage 4d (2026-10-01)

A part whose lifetime has ended is marked `ended`, which stops `send_due` sending more pieces and lets `settle` mark it done once its broker orders have finished. `end_lifetime` ends a waiting part as `expired` at once; a working one is cancelled, made marketable, or cancelled and closed. A close placed by `close_filled` has the role `<path>.close`, so it is not one of the part's own legs and its fill does not count as the part's trading; the part is marked done with reason `closed` as soon as the close is sent, as today's time stop records `completed` then. A lifetime ending `marketable` makes the part read prices, so the plan remembers the tick size it needs to round the new price.

## Stage 5a (2026-10-01)

`overrides` holds the order's own body values. `context` builds the `OrderContext` every pricing, execution, trigger, guard, modifier and lifetime is given, and `place` places through it so the broker order carries the order's instrument. An order naming its own `tag` keeps it even when it is not the plan's main order. `instruments` lists the order's own instrument so the price ticker brings its quotes.

## Stage 5b (2026-10-01)

A part with a `position` is a close: `send` hands it to `_close_positions`, which closes through `PositionQuantity` and records `nothing_held`, `refused` when the book gave no price, or `working`. Its closing orders carry the part's path as their role, so the part settles as done once they finish. `close` sends the side opposite to the body's for any trigger that needs a side, as `protect` does, and counts as closing a position.

## Stage 5d (2026-10-01)

`fill_ratio` scales the target a Then join hands the part in `start` and `set_target`; a scaled target of zero leaves the part pending. `sized_by_fills` is set by the reader on a Then join's child, so a `parent_fill` quantity anywhere else is refused.

## Stage 5e (2026-10-01)

`opened_by` holds the paths of a Then join's first plan's orders, set by the reader on every order of the child. `_opening_side` reads the side those orders filled on, so a two-sided breakout's exits protect whichever side broke; with nothing filled, or outside a Then join, it is the body's side as before. An order with no `side` now sends its own body's side through `_sending_side`, rather than the opening side, which matters once the two differ: a legged spread's second leg names SELL while the first leg filled on BUY.

## Pieces with their own price and broker (2026-10-01)

`order` and `place` take a piece's own `price`, which a ladder's rungs use, and `place` a `broker_name`, which `send_due` reads from the execution's memory, where the freeze-limit execution puts the broker it chose.

## Triggers that already hold (2026-10-01)

`start` sends an order at once when its trigger needs no prices and already holds, rather than leaving it waiting for the next tick. Before `time_from` no such trigger could hold when a plan was placed, since the time triggers refuse a passed time; now `time_from` and the `account` condition can. For an account-conditional order whose condition already holds, this places it at once where today's type answers `armed` and places it a tick later.

## `against_delta` (2026-10-01)

The side is worked out in `_sending_side` rather than `sending_side`, because it needs the order's context to read whether the plan's option is a call. Nothing calls `sending_side` without going through `_sending_side`.

## Asking each cancel once (2026-10-02)

Every update settles the whole plan, and an Either join that cancels its siblings, or a set target that wants nothing more, asked again for every order whose cancel was still on its way, spending an order message each time; brokers count those against their daily limits. `cancel_once` keeps the leg ids whose cancel the broker accepted in the part record as `cancel_asked`. It writes no event of its own, because a parameters event per cancel would bury the log; the record reaches the event log with the next change that has a message, and after a restart before that, at most one cancel is asked twice. A refused cancel is not kept, so it is asked again. The discretion modifier's cancel is left alone, because it is followed at once by the order that takes its place.

## Held changes in the context (2026-10-02)

`context` writes a caller's `held_price` and `held_quantity` from the part record over the body, so every reader of the order's body, its trigger, pricing and the order sent, sees the change. It reads the record without copying it, since the context is built on every tick.

## A lifetime's condition reads prices (2026-10-02)

`needs_prices` and `instruments` now count a lifetime's `when` condition. Before, the only `when` was the account condition, which reads no quotes; a Repeat's `until` on a price, the first one that does, never held, because the plan read no quotes and kept no tick size for it.

## A caller's changes (added 2026-10-02)

`caller_change` in the part record is a signed number of units the caller added to or took from the order, and `total()` and `set_target()` add it to whatever the plan works out. It is a delta rather than an absolute quantity because a Then child's target keeps rising as the first plan fills: a stop cut by 4 should stay 4 short of the fill, not freeze at one number. `set_target` still stores the join's raw target, so its "changed" comparison is unaffected.

`keeps_caller_quantity` is True only for `AllAtOnceExecution`. A split execution counts what it has sent from its own broker orders, so a cut slice is made up by later slices with no bookkeeping, which matches today's iceberg, TWAP and participation types; recording a delta there as well would have counted the cut twice.

`with_caller_prices` runs before the cap and the post-only guard, so the plan's own guards still check a price the caller set. A trigger is only replaced when the priced body already has one, so a `native_stop` with `exit_if_gapped` that was sent as a marketable limit stays a limit; the gap check itself still uses the pricing's own trigger, which is a known gap.
