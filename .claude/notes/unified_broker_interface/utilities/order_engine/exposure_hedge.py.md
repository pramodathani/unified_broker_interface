# `exposure_hedge.py`

## Why this is exposure rather than delta

The Atlas calls this a delta or exposure-triggered hedge, and the delta half is not built. The engine has no option pricing model, no implied volatility surface and no risk-free rate, so it cannot compute a delta, and adding one would be building a pricing library inside an order engine.

What it does instead is take a number per unit from the caller. Passing 1 makes the measure a plain signed quantity, which covers a portfolio meant to stay inside a size limit. Passing a delta computed somewhere else makes it a delta hedge, recalculated against live positions on every tick.

That division is the right one rather than a compromise. Anybody running a delta hedge already has a model they trust; what they want from an order engine is the arithmetic against live positions and the order that follows, not a second opinion on what the delta is.

## Why a hedge in flight counts immediately

The positions document is written by a poller and is several seconds behind. Without counting hedges already sent, the same hedge goes out on every tick until the first one fills and is polled, and the account ends up hedged several times over in the wrong direction. The offline scenario showed it on the very first run: one position out of band, two identical hedges on two consecutive ticks.

So a hedge leg that has not been rejected or cancelled counts towards the exposure straight away. For the few seconds between a hedge filling and the positions catching up it is counted twice, which makes the position look more hedged than it is, so the engine waits rather than hedging again. That is the conservative direction and it settles by itself.

## Why the band is required

A band of zero would send an order every time a price moved a paisa. There is no sensible default width, because it depends entirely on what is being hedged and how much churn the account can afford, so both edges are required and the caller has to have thought about it.

The hedge is sized to bring the exposure back to the middle of the band rather than to its near edge, so that a small further move does not immediately trigger another one.

## Why the hedge instrument gets its own quote and tick size

Until 2026-10-01 a hedge in an instrument other than the order's own was never sent. The price ticker fetched quotes only for the parent's `instrument_id`, `watch_instrument_id` and the instruments of existing legs, so the first hedge found no quote for `hedge_instrument_id`, `hedge_price` returned None, and nothing went out. The only offline scenario used the same instrument for the order, the watched position and the hedge, which is why it was missed. `PriceTicker.instruments_of` now adds `hedge_instrument_id`.

The tick size kept on the parent was also the order's own instrument's, while the only price this type computes is the hedge's. `remember_tick_size` is overridden to keep the hedge instrument's tick size. The scenario `an_exposure_hedge_prices_a_hedge_in_another_instrument_from_that_instruments_quote` hedges a RELIANCE equity position with the RELIANCE future, whose tick of 0.1 differs from the equity's 0.05, and sent nothing against the old code.
