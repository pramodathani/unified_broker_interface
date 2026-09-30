# Notes on `unified_broker_interface/utilities/order_engine/utilities/order_part.py`

## Why an order part only looks at legs with its own path

Every broker order the part places carries its path as its role, and `own_legs` filters on it. This is the ownership rule the design depends on: today's types find their legs by role names such as `entry` or by counting every leg, which is what stops two types sharing a parent.

## Why the done reasons are these four

`filled`, `partly_filled`, `refused` and `cancelled` separate the outcomes a caller acts on differently. `partly_filled` ends the parent as `completed`, matching `SyntheticOrder.finish_with_legs`, which treats any traded quantity as a completed parent. A leg in `unknown` is not finished, so a part with one is not done, for the same reason `OrderLeg.is_finished` gives: treating it as done could leave a position unprotected.

## Why `expanded` writes the defaults out as words

A dry run shows the plan as it would run. With only the `simple` preset there are no slot values yet, so each slot's default is described in words, such as "the body's quantity", until later stages give the slots real values that can be written out as data.
