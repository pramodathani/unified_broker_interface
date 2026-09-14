"""
Brokers' positions rows, kept for what the order modules share with them.

`/api/portfolio/positions` answers from `unified:portfolio:positions`, which `bin/unified/positions` keeps, so nothing
here serves it. What remains is what the orders modules in `broker_orders/` build on: `base.py`, with the position's
shape and the venue vocabulary, and the Fyers and Groww modules, whose segment codes their orders modules read.
"""
