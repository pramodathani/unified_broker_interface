# breakeven_price.py

`BreakevenPrice` solves the round trip's profit equation for the exit price instead of iterating: every statutory charge is a fixed share of a side's value, so the equation is linear in the exit price. Brokerage is the flat per-order fee from `unified.broker_order_costs`, taken for two orders, with GST on it.

`exact_price` rounds to four places away from the entry (ceiling for a bought position, floor for a sold one) and `price` then rounds to the tick in the same direction, so the answer never understates the move needed. `test_runs.trade_charges` checks, for both sides and with and without brokerage, that an exit at `price` nets zero or more and one tick worse nets less than zero.

This is the floor of the stop only. The tripwire (floor plus the measured slip of stops, from `unified.order_execution_costs`) and the switch-on distance (tripwire plus price flicker) are the next stages, described at the end of `docs/architecture/trade-charges.md`.
