"""What each filled order cost beyond brokerage: the price moves, spread and market impact between deciding to trade and the fill.

`execution_cost_measurement.py` reads the order engine's event log and the stored tick history for a range of days and writes one row per filled leg to `unified.order_execution_costs`. `leg_execution.py` folds one leg's events, `quote_moment.py` holds the best bid and ask at one moment, and `execution_cost.py` splits one leg's cost into its parts. `bin/unified/orders/execution_costs` runs the measurement every weekday night.

The taxes and fees a trade pays are kept apart from those price costs. `charge_rate_table.py` holds `unified.charge_rates`, the statutory rates per segment and category, `trade_charges.py` works out every charge on the rupees bought and sold, and `breakeven_price.py` gives the exit price at which a position makes exactly nothing after them.

A stop fills beyond its trigger, so a breakeven stop needs its trigger beyond the breakeven. `stop_slippage_measurement.py` follows every fired protective stop to the fill that closed its position and writes `unified.stop_slippage`, one `StopOutcome` from `stop_outcome.py` per stop, and `bin/unified/orders/stop_slippage` runs it every weekday night. `stop_slip_allowance.py` reads those rows into a percentile of the slip per segment and side, and `tripwire_price.py` places the trigger far enough beyond the breakeven that a stop slipping by that much still closes on it.
"""
