# Notes on `unified_broker_interface/utilities/order_engine/utilities/option_model_pricing.py`

## Why it copies the volatility type's rules

The expiry at 15:30 IST, the forward rule, the 500 percent ceiling on volatility and the body's price as the worst accepted are those of `volatility_order.py`. The offline scenarios `a_plan_volatility_order_*` send the same requests at the same prices as `a_volatility_order_*`.

## The clock

The first premium is worked out with `time.time()`, as today's type does at placement, because `priced_body` is not given the tick's time. Later moves use the tick's time. The second example program gives its option an expiry in 2099, so its output does not depend on the day it runs.

## Caller's change, bounds and expiry (2026-10-05)

`carry_on` used to be inherited from `FollowInstrumentPricing`, which stored a start price the model never reads, so a caller's price was undone on the next tick although the docs promised the implied volatility would be kept, as the retired class did. It now finds the implied volatility with `Black76.implied_volatility` and keeps it in memory as `volatility`; `volatility_now` prices from it. The body's worst price is applied after the bounds, so a `lowest_price` above a buy's price no longer bids above it. An option already expired is refused in `prepared_memory` with 400 instead of being armed for ever. A tick after a caller's change can still move the order one tick, from time decay and the passive rounding.
