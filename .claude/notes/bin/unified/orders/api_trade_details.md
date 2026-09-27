# Notes on `bin/unified/orders/api_trade_details`

## Why each row carries the order engine's parent

With every order placed through the order engine, a caller who placed a bracket or a list needs to find its broker orders in the day's book. `EngineLinks` joins each row to `unified:orders:children` and `unified:orders:parents`, in at most two round trips per pass, and adds `engine_parent_id`, `leg_role`, `synthetic_type` and `intent_id`, None for anything the engine did not place. The class is written out in both combiners rather than shared, because each script in `bin/` is self-contained.
