# Notes on `unified_broker_interface/utilities/order_engine/utilities/top_up_execution.py`

## Why a new execution

`all_at_once` grows by changing its one order, which is right for a bracket's exits. Today's attached hedge and legged spread instead send a new order for what is missing after each fill, so each order keeps the price it was given, which for the second leg of a spread is the price worked out from the fills so far. `top_up` is that rule as an execution, so the presets send the same requests as today's types (`a_plan_attached_hedge_*`, `a_plan_legged_spread_*`).
