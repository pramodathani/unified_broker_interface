# Notes on `unified_broker_interface/utilities/order_engine/two_sided_quote.py`

## Why it subclasses `Grid`

A two-sided quote is a grid of one level on each side that moves with the market. `Grid` already counts the inventory its fills built, knows which side adds to it, enforces the required `most_inventory` cap, builds a limit for a side and settles the first answer. What this type adds is the re-pricing, the lean and the re-quoting, all in `on_price_tick`.

## Why a fill is handled on the next price tick

`Grid.on_leg_update` places the opposite rung one step away. Here a fill changes where both quotes belong, through the lean, so re-quoting the filled side and re-pricing the other are one decision that needs the live quote. The price ticker supplies it within about a second, so `on_leg_update` does nothing and `on_price_tick` does both.

## How the lean is measured

The lean is `inventory ÷ quantity × skew_ticks` ticks: one order's worth held moves both quotes by `skew_ticks`. Measuring in orders rather than units keeps `skew_ticks` meaningful whatever the quote size.

## How the offline suite modifies numbered orders

A modify is built from the broker's own book entry, so `price_result` now seeds an entry for every order `NumberingBrokerNetwork` numbered while the parent was placed, not only for the fixed order id.
