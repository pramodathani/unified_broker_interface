# Notes on `unified_broker_interface/utilities/order_engine/underlying_peg.py`

## Why the delta is fixed

The Atlas's G6 formula uses the delta the caller states. A real option's delta changes as the underlying moves, so over a large move a fixed delta drifts from fair value. Re-computing it would need an option pricing model, which is what the volatility order (G7) and its `Black76` helper are for. A caller who wants the price to track a changing delta can re-send the order, or change its price, which re-anchors it.

## Why it reuses `watch_instrument_id`

`PriceTicker.instruments_of` reads `watch_instrument_id` from a parent's parameters to know which extra quote to fetch before it builds any order type. Using the same name means the ticker needs no change, and it is the name `cross_instrument` already uses for the same idea.

## Why a step is measured against the leg's price

`step_ticks` compares the new target with the price the leg rests at now, not with the last target. A run of small moves in one direction therefore adds up and eventually moves the order, whereas comparing tick to tick would let a slow drift never reach the step.

## How the test suite gives it a second quote

`price_result` in `test_runs/order_engine.py` seeds only RELIANCE's quote. A step can now carry `other_quotes`, keyed by a name in `INSTRUMENT_IDENTIFIERS`, and they are seeded before the order is placed and on each tick. The scenarios use the Nifty index as the underlying and RELIANCE as the traded instrument.

## Why `number`'s message names the parent's type

`VolatilityOrder` inherits `number`, so its refusal names whichever type the parent is ("an order of type volatility needs volatility") rather than always saying underlying peg.
