# Notes on `unified_broker_interface/utilities/order_engine/good_till_time.py`

## Why `at_expiry: market` modifies to a limit rather than to a market order

The Atlas's G5 is a limit that becomes a market order at a set time. The engine never sends a true market order to take liquidity, because a market order in a thin book fills at any price, and several Indian brokers refuse market orders on some segments. So `make_marketable` modifies each resting leg to a limit `DEFAULT_BUFFER_TICKS` (two) ticks past the other side's best price, or past the last traded price when that side is empty. That takes what is at the touch and a little beyond, which is what a caller asking for "market at 14:30" means.

The tick size is remembered in `run`, only when the action is `market`, because the price has to be rounded when the time comes and the instrument's agreed tick size may not be readable then. `made_marketable` is recorded with `record_parameters`, so the parent does not reprice again on the next clock tick or after a restart.
