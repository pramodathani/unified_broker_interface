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
