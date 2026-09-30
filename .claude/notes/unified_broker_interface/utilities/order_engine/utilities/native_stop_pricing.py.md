# Notes on `unified_broker_interface/utilities/order_engine/utilities/native_stop_pricing.py`

## Why the settings are `trigger_price` and `limit_price`

They are the two prices every broker's stop-limit takes, and the names match `stop_price` and `stop_limit_price` in `ExitLegs` closely enough to map one to the other when bracket and cover become presets in step 2b. A `limit_offset` form, a distance from the trigger, was left out until a preset needs it.
