# Notes on `unified_broker_interface/utilities/order_engine/utilities/book_depth_execution.py`

## Why it copies the liquidity-seeking type's rules

Adding up every level of the opposite side no worse than the limit, striking only when that reaches `minimum_quantity`, and striking for the smaller of what is shown and what is left are the rules of `liquidity_seeking.py`, so the `liquidity_seeking` preset sends what today's type sends. Its price comes from the order's pricing, which the preset makes `fixed` at `limit_price`, so a strike that does not fill rests at the limit as today.

## Why remaining counts resting strikes

A strike that partly fills rests, and counting the whole of a resting strike means the next strike is only for what is neither traded nor resting; otherwise the order could end up with more resting than its quantity. A rejected strike stops the order, for the same reason a rejected piece stops an iceberg.

## Prices from the book

Book prices are read through `MarketView.number`, which snaps them to the tick, because a quote's JSON floats arrive as values such as 1000.0999999999999 and an unsnapped comparison with the limit would skip a level that is exactly at it.
