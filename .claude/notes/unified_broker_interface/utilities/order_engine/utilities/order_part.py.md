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
