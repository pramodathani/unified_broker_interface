# Notes on `unified_broker_interface/utilities/broker_selection/round_robin.py`

## Why the counter moves past the brokers passed over

The first fix tried ranking only the brokers able to take the order. It spread orders evenly, but it moved the counter's meaning: `order_routes` seeds the counter so each per-broker scenario lands on the broker it is named after, and 59 of them landed elsewhere. Moving the counter on by the number of brokers passed over, after the choice, leaves every single choice exactly as before and removes the double turn for the next order; the `skipped` list keeps its meaning too. `EnginePlacement.prepare` calls `record_passed_over` only when the selector itself chose, so an order counts once, at intake. The check `after_market_orders_are_spread_evenly_over_the_brokers_that_take_them` in `test_runs/order_engine.py` gives each of the seven after-market brokers 4 of 28; without the change INDmoney gets 9 and Dhan 2.
