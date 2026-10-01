# Notes on `unified_broker_interface/utilities/order_engine/utilities/option_model_pricing.py`

## Why it copies the volatility type's rules

The expiry at 15:30 IST, the forward rule, the 500 percent ceiling on volatility and the body's price as the worst accepted are those of `volatility_order.py`. The offline scenarios `a_plan_volatility_order_*` send the same requests at the same prices as `a_volatility_order_*`.

## The clock

The first premium is worked out with `time.time()`, as today's type does at placement, because `priced_body` is not given the tick's time. Later moves use the tick's time. The second example program gives its option an expiry in 2099, so its output does not depend on the day it runs.
