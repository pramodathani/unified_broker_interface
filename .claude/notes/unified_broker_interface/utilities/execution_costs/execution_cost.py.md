# Notes on `execution_cost.py`

## Why the parts are measured on the mid-price

The first sketch measured latency as the move of the touch (the ask for a buy) between sending and the answer. That mixes two things: a move of the market and a change in the spread. Measuring delay and latency on the mid-price keeps them as pure market moves, and the spread is then accounted for once, as the half spread when the broker answered. The four parts then add up exactly to the total, which the first real run confirmed to four decimal places on all 175 rows.

## `beyond_touch` instead of "impact"

The last part is the fill's distance past the best price on its side. For an order that crossed the spread and took more than the first level, that is market impact. For a resting limit order filled inside the spread it is negative, which an "impact" column would make look like a bug. The neutral name and the docstring explain both cases.

## Signed zeros

`Decimal` keeps the sign of zero, so a sell leg whose mid-price did not move came out as `-0.0000`. `without_sign_on_zero` removes the sign before a figure is rounded into a row or a basis point.
