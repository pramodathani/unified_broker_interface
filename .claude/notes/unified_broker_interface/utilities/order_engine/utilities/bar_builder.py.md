# `bar_builder.py`

## Why the bars are built here rather than read from the price history

Reading `unified.price_history` would give proper bars going back years. It would also put a PostgreSQL query inside the order path, on a tick that currently costs one `HMGET`, and make two order types depend on the daily history job having run — which is a job that can fail for reasons that have nothing to do with trading.

Building bars from the engine's own one-second samples costs nothing and gives bars that start when the order was placed. That limitation is real and both types that use it say so out loud rather than leaving somebody to discover that a fourteen-period average was never available on an order placed at ten past three.

If it ever becomes worth having proper history, the shape to reach for is a warm-up read at placement that seeds `closed_bars` from the database and leaves the live path alone.

## Why the bars are built from samples rather than trades

A one-second tick carries the last traded price at that moment, so a high that happened and was traded through between two ticks is missed. For a fifteen-minute bar sampled nine hundred times that is a small error. For a one-minute bar on an instrument that trades once a minute it is not, and the shorter the bar the less the range is worth trusting.

That is stated in the class docstring because it bears directly on the average true range: a systematically understated range makes an average-range trail systematically too tight.

## Why bars align to the clock rather than to the order

`bar_start` floors the moment to a multiple of the bar length, so a fifteen-minute bar starts at a quarter past the hour. Aligning to when the order was placed would mean two orders on the same instrument disagreeing about where the bars are, and neither of them agreeing with the chart the person placing them was looking at.

## Why everything is stored as text

The bars live in the parent's parameters, which go through JSON and Redis. A price stored as a float comes back as a float, and a bar high of 1000.10 becomes 1000.0999999999999 — the same problem recorded at length in `PriceReference.number`, arriving by a different route. Text and `Decimal` at the boundaries avoid it entirely.
