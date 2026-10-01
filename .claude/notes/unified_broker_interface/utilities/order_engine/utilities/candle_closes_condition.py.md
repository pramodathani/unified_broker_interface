# Notes on `unified_broker_interface/utilities/order_engine/utilities/candle_closes_condition.py`

## Why it copies the candle close stop's rules

Bars of `bar_minutes` built from the last traded price with `BarBuilder`, an answer only when a bar closes, and the hidden stop's default direction are the rules of `candle_close_stop.py`. The offline scenarios `a_plan_candle_close_stop_*` send the same requests as today's. Today's type watches the last price for its bars while its plain hidden stop watches the opposite touch; this condition uses the last price, as the candle close stop does.

## The bars across a restart

The bars live in the trigger's memory, which is saved with the parent on every tick but recorded with an event only when the order fires, so a restart can lose a bar in progress, as today's type loses whatever was saved without an event. The next bar is built afresh, which can delay an exit by one bar, never fire one early.
