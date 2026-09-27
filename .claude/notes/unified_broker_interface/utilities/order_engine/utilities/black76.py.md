# Notes on `unified_broker_interface/utilities/order_engine/utilities/black76.py`

## Checks made when it was written

An at-the-money Nifty call six days out at 12.5% volatility prices at 159.84, against 159.82 from 0.3989 × forward × volatility × √time. The call and put at the same strike differ by exactly the discounted forward minus strike (zero at the money with no rate), which is put-call parity. `implied_volatility` recovers 12.5% from the call's own premium.

## Why implied volatility is found by halving

A premium rises steadily with volatility, so halving the interval between 0.01% and 500% a hundred times always converges, needs no derivative and is short enough to read. Newton's method is faster but can overshoot for deep in- or out-of-the-money options, and speed does not matter for one calculation per caller's modify.

## Why floats

A premium from a model is an estimate. It is converted to a `Decimal` and rounded onto the tick only when it becomes an order price, which is where exactness matters.
