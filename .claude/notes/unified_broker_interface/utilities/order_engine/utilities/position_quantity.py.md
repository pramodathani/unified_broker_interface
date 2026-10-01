# Notes on `unified_broker_interface/utilities/order_engine/utilities/position_quantity.py`

## Why it uses `PositionCloser`

Today's close on trigger, square off and stop and reverse all close through `PositionCloser`, which reads each broker's positions hash and the broker-token map, cancels resting orders through `cancel_outside_order`, and builds a limit two ticks past the touch. The plan order is a `SyntheticOrder`, so it can be the closer's runner unchanged, and the offline scenarios `a_plan_close_on_trigger_*`, `a_plan_square_off_*` and `a_plan_*stop_and_reverse_*` send the same requests at the same prices as today's.

## Read first, cancel second

Today's close on trigger cancels first and then reads; today's square off reads first and cancels on the instruments it found. Here the positions are read first and the cancels go out before any close, so both orders of events are kept where they matter: nothing is closed while something still rests. For `every_instrument` the instruments cancelled on are those found holding a position, as square off does.

## The design's `position_broker` venue

The design names a `position_broker` venue for this. It is not a separate setting: a close always sends each broker's share to that broker, which is the only sensible venue for a close and what fixes today's square off's wrong-broker problem.
