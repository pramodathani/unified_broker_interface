# Notes on `unified_broker_interface/utilities/order_engine/utilities/marketable_pricing.py`

## Why it copies market-if-touched's arithmetic

The price is `MarketView.moved` from the opposite touch by `buffer_ticks` towards the market, then `MarketView.rounded` for the sending side, exactly as `market_if_touched.py` and `hidden_stop.py` price their child orders, so a preset built on it sends the same price as today's type. The buffer default of 2 is the same `DEFAULT_BUFFER_TICKS` those types use.

## Why no price means waiting, not refusing

On a tick the book may briefly have no opposite side, or a quote may not have arrived. Returning None keeps the part waiting for the next tick, as today's triggers do. Only an order with no trigger, priced when the plan is placed, is refused with 503 when no price can be made, because there is no later tick for it.

## Stale quotes (2026-10-05)

`priced_body` gives no price from a quote marked stale, as every moving pricing has since pull request #66. An attached hedge was sent at once from a stale quote; it now waits, and `unpriced` makes every tick try again.
