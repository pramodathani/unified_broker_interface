"""What each filled order cost beyond brokerage: the price moves, spread and market impact between deciding to trade and the fill.

`execution_cost_measurement.py` reads the order engine's event log and the stored tick history for a range of days and writes one row per filled leg to `unified.order_execution_costs`. `leg_execution.py` folds one leg's events, `quote_moment.py` holds the best bid and ask at one moment, and `execution_cost.py` splits one leg's cost into its parts. `bin/unified/orders/execution_costs` runs the measurement every weekday night.
"""
