# Notes on `unified_broker_interface/utilities/order_engine/plan.py`

## What this is the first stage of

`PlanOrder` is stage 1 of the composable synthetic orders design written on 2026-10-01 (the "Composable synthetic orders: design" document). The goal is one order that combines any number of the existing types through slots (trigger, quantity, side, execution, pricing, guards, venue, lifetime) and joins (then, either, together, using, repeat, sequence). Reading all 53 existing types showed that each assumes it owns the whole parent: memory in one flat `parameters` dictionary, legs found by role names such as `entry`, TWAP counting every leg, triggers treating any leg as proof of firing. So the new engine is built beside the old types rather than inside them, and the old types stay until each has a preset proven live.

## Why it is registered as one more synthetic type

Registering `plan` in `SYNTHETIC_ORDER_CLASSES` reuses everything the engine already does for a type: the intent loop, broker lanes, the engine lock, recovery from recorded events, rate budgets, daily caps and risk gates. The plan's own job is only to route events to its parts and decide when it is finished.

## Why the part state lives in `parameters['parts']`

The caller's `plan` stays in `parameters['plan']` exactly as sent, and what the engine learns goes into `parameters['parts']`, keyed by part path. Both are recorded with `record_parameters`, so recovery rebuilds them from `parameters_changed` events, and `GET /api/orders/parents?parent_id=` already returns the whole stored parent. The design document proposed a separate `GET /api/orders/plans/{parent_id}` route; it turned out to be unnecessary for stage 1, because the existing route shows the parts already.

## Why legs carry the part's path as their role

`OrderLeg.role` is a free text field that is stored with every event (`leg_role` is `TEXT` in `unified.synthetic_order_events`), so putting the part's path there gives every part its own legs without changing the leg's stored shape. The design document described a separate `part_path` field; using the role is the smaller change and can be revisited if a part ever needs a role word as well as a path.

## Why the plan is read again on every event

A runner object is built afresh for every event, as for every other type, so the parts are rebuilt from `parameters['plan']` each time. The plan was checked in full when it was placed, so reading it again cannot fail for a stored parent.

## What stage 1 deliberately leaves out

The per-slot merge rules and the contradiction checks described in the design are not written yet, because stage 1 has no slot values for them to check; they arrive with the stages that add those values. A plan is one `order` node, and the only preset is `simple`. Joins are recognised by name and refused as not built yet.

## Stage 2a: triggers, the protect side and pricing (2026-10-01)

A plan's order can now wait for a trigger, protect a position and be priced by one pricing rule. `PlanOrder` sets `WANTS_PRICES`, answers `202 armed` for an order with a trigger, and on each tick asks the root part whether its trigger holds, placing the order once. The part's record gains `memory`, what the trigger remembers, and `fired_at`. Confirmation counts are written to Redis on each tick without a recorded event, as today's price triggers do; the change of state to `working` is recorded, and a restart between ticks was checked offline to still fire once.

The memory is deep-copied before a tick, because the trigger mutates nested dictionaries in place; a shallow copy made the "did it change" comparison always false, so a `held` trigger never saved when the level was first reached. The offline scenario `a_plan_held_trigger_waits_until_the_level_has_held` caught it.

A standalone `protect` order is refused with 409 and `protect_needs_position` when the unified positions document shows no position on the body's side, as the user decided on 2026-10-01. It reuses `ReduceOnlyCheck.held`. The reduce-only check itself is not applied to `protect` orders, because a protecting child of a Then join in step 2b will be placed the moment its parent fills, before the positions document has caught up.

`closes_position` returns True for a leg of a `protect` part, so it may use the part of a broker's daily cap kept for exits. Instruments a trigger watches are listed in `parameters['watch_instrument_ids']`, which the price ticker reads.

## Stage 2b: the Then and Either joins (2026-10-01)

The plan is now a tree of `OrderPart`, `ThenPart` and `EitherPart`. When the plan is placed, every order part gets a `pending` record, with its trigger prepared, so a time already passed anywhere in the plan is refused at once. After every event the whole tree is settled and the parent ends when the root is done: `completed` when anything traded, `rejected` when a broker refused an order and nothing traded, `cancelled` otherwise.

A tick checks every waiting order part in the tree, not only the root. `fired_at` is written before the order is sent, so the placement's recorded event carries it and a restart does not lose it; it is removed again if no price could be made.

The answer is the single broker answer when the root is one order placed at once, as in stage 1; `202 armed` when nothing was placed; otherwise `legs`, one entry per order placed. `part_record`, `set_part_record` and `quotes_now` are public because the parts call them.

A plan with an order that cannot be priced at once now waits for the next tick instead of being refused with 503, since a waiting order is retried on every tick.

The offline scenario `a_plan_bracket_behaves_the_same_with_a_restart_between_fills` rebuilds the parent from its recorded events after every fill and sends the same eight requests as the run without restarts.

## Stage 2c: trailing (2026-10-01)

A working part whose pricing moves, marked `moves` in its record when the plan is placed, is offered every price tick and moved through `OrderPart.move`, which calls `reprice_leg`. `PlanReader` now gets the body's `transaction_type`, because a `trailing_stop` preset with `activate_at` has to know whether the position is long or short to know which way the activation level is reached.

## Stage 3a: execution (2026-10-01)

A part whose execution is paced by ticks is marked `paced` when the plan is placed, and every price tick calls its `send_due`. The design's nesting of executions and the Using join are not built in this stage: none of the stage's presets needs them, and the design's worked example, a trailing stop exiting through TWAP, is a `trails` trigger with `twap` execution on one order (offline scenario `a_plan_trailing_exit_sells_through_twap_once_the_price_pulls_back`).

## Stage 3b: participation and liquidity seeking (2026-10-01)

Executions now receive `sending_side` in `due_pieces`, because `book_depth` has to know which side of the book it would take from. `OrderPart.send_due` saves the execution memory with an event after placing, so participation's `counted_volume` survives a restart (offline scenario `a_plan_participation_keeps_its_count_across_a_restart`).

An order whose execution is paced by ticks now starts working when its trigger holds even if nothing is due, rather than going back to waiting. Before this, a `scheduled` participation began counting, sent nothing on that tick, went back to waiting and was not saved, so every later tick began counting again from the new volume and nothing was ever sent (offline scenario `a_plan_participation_that_starts_at_a_time`). `on_price_tick` keeps `fired_at` and saves the parent in that case.

The freeze quantity is not an execution yet. Each broker publishes its freeze limit in its own units and the broker is chosen only when a piece is placed, so splitting at the freeze limit belongs with nesting, where it would be applied innermost to every piece.

## Stage 4a: moving prices, cap and post-only (2026-10-01)

`on_price_tick` passes the tick's time to `OrderPart.move`, because a chase steps on a clock. A guard that refuses an order leaves the part `done` with reason `refused` and a `message`; `_guard_refusal` finds it, so `_finish_if_done` ends the parent as `rejected` and `_answer` answers 409 with the message when nothing was placed.

## Stage 4b: following another instrument and discretion (2026-10-01)

Every order part's pricing memory is readied when the plan is placed through `OrderPart.prepared_pricing_memory`, so the option model's strike and expiry are read once and recorded with the received event; a refusal there answers before anything is recorded. A part is marked `moves` when its pricing moves or it has discretion. `quotes_now` reads every watched instrument as well as the order's own, so an order priced from another instrument is placed at once.

## Stage 4c: average-range trail and stepped stop (2026-10-01)

Nothing in the plan order changed for this step; `AtrTrailPricing` and `StagesPricing` are pricings that move, and every stop pricing is listed once as `STOP_PRICINGS` in the reader.

## Stage 4d: lifetimes (2026-10-01)

`PlanOrder` now sets `WANTS_CLOCK`, so the clock ticker gives every open plan `on_clock_tick` once a second and an order ends on time even when its instrument stops quoting; a plan with no lifetime returns at once, after reading only its part records. Each part's `ends_at` is worked out when the plan is placed and recorded with the received event. `_end_lifetimes` runs on both kinds of tick, before anything else on a price tick; on a clock tick it reads quotes only when an order is to be made marketable. A close sent by `close_filled` has the role `<path>.close`, which `closes_position` counts as closing, so it may use the exit reserve of a broker's daily cap.

## Stage 5a: orders on several instruments, together and sequence (2026-10-01)

`_remember_tick_sizes` keeps the tick size of every other instrument a priced order trades. `_refuse_without_position` checks a protecting order against the position on its own instrument and product. A multi-order answer names each leg's `instrument_id`. `group_margin_legs` is set by a together join while its children start; it is a class attribute holding None so a plan order that never builds a group has it.

## Stage 5b: closing what is held (2026-10-01)

`_fire_waiting` is shared by price and clock ticks. A clock tick looks only at orders whose trigger needs no prices, because a price trigger may count ticks to confirm, and reads quotes only for an order that fires and prices itself; before this, a time trigger in a plan fired only on a price tick, so a square off whose instrument sent no tick never ran. A tick on which an order fired and ended without placing anything now settles and finishes the plan. A plan whose only work was a close that found nothing held ends `completed` even from `received`, as today's close types record, though the usual state changes do not allow it; recovery replays whatever was recorded.

## Stage 5g: plans that outlive the day (2026-10-01)

`PlanOrder` sets `CARRIES_OVERNIGHT`, so recovery reads every plan's events from the carry window, 366 days since 2026-10-04 (it was 30, which silently dropped a GTT valid for longer once it was a month old), but `carries_parent_overnight` keeps only a plan whose parameters say `carries_overnight`, which `run` sets when any order has a lifetime in `after_days`. Every other plan is a day's plan: rebuilding it after the 06:00 reset would revive yesterday's waiting orders and let them fire, which the reset's expiry of the parent caches has always prevented. The cost is a larger carry read, every plan of the last 366 days, twelve times the old 30-day read. That is acceptable at today's volumes and is the first thing to narrow if it is not, for example by reading only the parents still open in the Redis cache before the rebuild.

## Paced orders on the clock (2026-10-01)

A clock tick now also sends the due pieces of every working paced order, reading the quotes as they are now for one that prices itself. Today's timed types are clock-driven, and a daily stop on an instrument with no price tick at 09:20 would otherwise not be placed. Sending on both kinds of tick is safe, because an execution works out what is due from the orders already sent.

## Paper fills and missed quantity (2026-10-01)

`_fire_waiting` hands a paper order to its venue instead of asking its trigger, and reports a fill the same way as an order that ended without placing anything, so the plan settles, finishes and saves. An order on a `limit_marketable` trigger records `missed_quantity` in its part record as it fires, from the queue estimate, as today's type records it in the parent's parameters.

## Combined answers and kept-whole memory (2026-10-02)

A plan that placed several orders used to answer with the outcome of the first order that was not accepted, or `accepted` once any was, which hid a refused rung behind a 200. It now combines the outcomes with `combined_answer`, as today's grid and basket do, so a mix answers `partial` with 207. No earlier plan scenario had a mix, so none changed.

`run` also asks every part for `prepared_own_memory`, which only kept-whole parts give, and keeps it as `own_memory` in the part record before the parent is recorded.

## A first order placed on a tick (2026-10-02)

An exposure hedge places its first order from `move` on a tick, not from `start`, and orders placed in `move` never pass through `_after_placing`, so the parent stayed `received` with a hedge resting. `_after_first_moves` hands the legs' recorded outcomes to `_after_placing` after any tick on which a part moved, while the parent is still `received`. Parts that only reprice what they already placed reach it with the parent already `working`, so it changes nothing for them.

## Changing a held order (2026-10-02)

`modify_held` is today's virtual limit rule for a plan: it finds the one order waiting on a `limit_marketable` trigger, checks the change as today's type does, and keeps the new price and quantity as `held_price` and `held_quantity` in the part record, which `OrderPart.context` writes over the body, so the trigger's limit and the order sent both use them. The held terms in the trigger's memory change too, for the virtual book. A request names only the parent, so a plan holding several such orders is refused with 409 rather than guessing which one is meant.

## Daily repeats and lifetime conditions (2026-10-02)

A part marked `spans_days`, a daily Repeat's copy, carries the plan overnight as a lifetime of days does. `run` also prepares a lifetime's `when` condition and keeps its memory as `lifetime_memory` when there is any, so a time condition used as a Repeat's `until` works out its moment; the account condition keeps nothing, so plans that had one are unchanged.

## A caller's changes (added 2026-10-02)

Before this, `PlanOrder` had no `on_leg_modified` or `outside_change_problem`, so `PUT /api/orders/modify` on a plan's broker order was sent and recorded, but the plan then undid it: a trailing stop's next tick moved the caller's trigger back, a peg moved the price back, a chase stepped away in the same tick, a bracket exit could be raised above the position, and a cut exit grew back on the next settle. Offline probes reproduced each one before the fix, and `run_plan_change_checks` in `test_runs/order_engine.py` now pins the fixed behaviour.

`on_leg_modified` finds the part by the leg's role, which is the part's path. It reads quotes only when a price moved, because only the peg and the followed-price pricings need them. A quantity change on a `reduce` Either's direct child goes on the join rather than the part, so the sibling exits follow it, which is what today's OCO does; elsewhere it goes on the part, and only for an order sent all at once (see `order_part.py.md`). The plan is settled straight after, so the other exit is resized in the same command rather than on the next fill.

`modify_part` is the user's choice on 2026-10-02 to let modify also change parts that have not been sent, which the older types cannot do. It goes through the existing `modify_held` engine command (with `part` in the arguments) instead of a new command, so the route, the list form and the handoff needed no new plumbing. Prices are allowed only on `FixedPricing` and `NativeStopPricing` parts, because a moving pricing works its price out at send time and a caller's fixed price would fight it. Quantity is refused for a part sized by an earlier part's fills (`opened_by` or `sized_by_fills`), because its total does not exist yet; a delta on an unknown total was considered and rejected as confusing. A part held on `limit_marketable` delegates to `_change_held_part`, the old body of `modify_held`, so held orders keep exactly one code path. The tick and lot checks moved into `_check_ticks_and_lots`, shared by both.

A caller's loosened trailing stop still snaps back when the market is already above the new best price. That is the older trailing stop's rule too (checked side by side offline), so it was kept for parity rather than changed.

## A caller's cancels (added 2026-10-02)

Before building `cancel_part`, offline probes checked what a plan does when a caller cancels one of its broker orders through `cancel_leg`, which had worked since the plan engine began. It never sent the cancelled order again, and each case matched the older type: an iceberg stopped, a TWAP skipped the slice and finished `partly_filled`, a bracket whose entry was cancelled dropped its exits, a cancelled bracket stop left the target resting. Those are now pinned in `run_plan_cancel_checks` in `test_runs/order_engine.py`.

`cancel_part` is the user's choice on 2026-10-02 to let cancel name a plan part, whether or not it has sent orders. A working part is marked `ended`, the flag a lifetime that runs out already sets, so `send_due` and `settle` already knew to send nothing more and to mark it done when its orders finish. A part whose turn has not come is also marked `ended` but left `pending`; `OrderPart.start` then marks it done without sending. Marking it done at once was tried first and was wrong: `is_started` counts a done part as started, so a Then join believed its Either child had started, set the shared quantity to the entry's fill of zero, and the target was cancelled with the stop. A kept-whole part that has not started is refused, as `modify_part` refuses it, because each kept-whole type has its own `start` and would need its own check. The answer reports each resting order's `cancel_accepted` from the part's `cancel_asked` list, which is exact without changing `cancel_once`; the broker's full answer is in the event log.

The tick no longer moves a part marked `ended`. Before, a peg or trail whose lifetime had ended could be repriced while its cancel was on its way; no recording moved when this changed.


## Refusals when an order fires (2026-10-04)

A placement refused as a part fired, such as a fixed price off the tick or a reduce-only order with nothing to reduce, used to escape `_fire_waiting`, be logged by the ticker, and leave the part `waiting`, so it was refused again on every tick while the caller only ever saw `202 armed`. A refusal with a status in `PERMANENT_REFUSAL_STATUSES` (400, 404, 409) now ends the part as `refused` with the refusal's message, and the plan finishes as usual. Other statuses, such as 429 for a daily cap or 503 for no broker, are still raised and tried again on the next tick, because they can clear by themselves.

`_refuse_off_tick_prices` also refuses a fixed price off the tick when the plan is placed, which covers every triggered order, because those read prices and so `remember_tick_size` has just read the tick at no extra cost. A fixed price on an order sent at once needs no such check, since the placement refuses it straight away.
