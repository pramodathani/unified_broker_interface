# Notes on `unified_broker_interface/utilities/order_engine/utilities/follow_instrument_pricing.py`

## Why it copies the underlying peg's rules

The formula, the bounds, the floor of one tick and the step are those of `underlying_peg.py`, so the `underlying_peg` preset sends what today's type sends; the offline scenarios `a_plan_underlying_peg_*` send the same requests at the same prices as `an_underlying_peg_*`. Today's answer also carries `underlying_start`; a plan answers with the broker's answer as it is.

## Where the start is kept

The start price and the watched price at sending are put in the pricing memory by `priced_body`, which `OrderPart.order` records with an event, so a restart keeps them (`a_plan_underlying_peg_keeps_its_start_across_a_restart`). The plan reads the watched instrument's quote when it is placed through `PlanOrder.quotes_now`, which reads every instrument in `watch_instrument_ids`, so the order is placed at once as today rather than on the first tick.

## Why `OptionModelPricing` subclasses it

Today's volatility type subclasses the underlying peg, and the two share the watched price, the bounds, the step and the moving. The subclass overrides only `prepared_memory`, `target_price`, `priced_body`, `reason` and `described`. `OrderPart` asks `isinstance(..., FollowInstrumentPricing)` to know that a pricing watches another instrument and readies memory when the plan is placed, which covers both.

## Not done yet

A caller who changes the price is not re-anchored, as with the peg.
