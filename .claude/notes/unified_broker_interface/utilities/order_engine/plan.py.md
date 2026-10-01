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
