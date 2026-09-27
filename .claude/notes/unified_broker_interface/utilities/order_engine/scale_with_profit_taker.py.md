# Notes on `unified_broker_interface/utilities/order_engine/scale_with_profit_taker.py`

## How each leg is tied to its rung

`rung_of_leg` in the parameters maps every leg id, rung or profit-taker, to the rung it belongs to, and `rungs` keeps each rung's price, quantity and cycle count. Both are recorded with `record_parameters`, so a restart rebuilds them from the event log. `handled_legs` lists the legs whose fill has already been acted on, because an order update for a filled leg can arrive more than once.

## Why a rung waits for a complete fill

Sending a profit-taker for each partial fill would split one rung into several small profit-takers, and re-arming would then have to add their fills back up. Waiting for the whole rung keeps one profit-taker per rung and one re-armed rung per profit-taker.

## How the offline scenario tells the legs apart

Every leg at the stub broker used to get the same order id, so an update could only ever reach the first leg. `NumberingBrokerNetwork` in `test_runs/order_engine.py` numbers placed orders `26091500000101` onward when an answer asks for it with `number_orders`. It lives in the engine suite rather than in `engine_stand_ins.py`, because importing `order_routes` from the stand-ins module made a circular import for the suites that `order_routes` itself imports.
