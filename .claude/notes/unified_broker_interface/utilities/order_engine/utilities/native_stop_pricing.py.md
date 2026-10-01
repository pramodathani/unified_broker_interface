# Notes on `unified_broker_interface/utilities/order_engine/utilities/native_stop_pricing.py`

## Why the settings are `trigger_price` and `limit_price`

They are the two prices every broker's stop-limit takes, and the names match `stop_price` and `stop_limit_price` in `ExitLegs` closely enough to map one to the other when bracket and cover become presets in step 2b. A `limit_offset` form, a distance from the trigger, was left out until a preset needs it.

## `exit_if_gapped` (2026-10-01)

Today's daily stop exits with a limit two ticks past the touch when the open has gapped past its stop, falling back on the last price when the book shows no other side. The option keeps that rule for any native stop, and makes the pricing read quotes only when it is set.
