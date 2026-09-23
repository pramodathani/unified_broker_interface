# `price_ticker.py`

## Why polling beats subscribing

The obvious design is to have the engine join the tick feed and react to every update for the instruments it cares about. It was rejected because of the shape of this system's feed rather than for any general reason.

`unified:quotes:live` is a hash covering every mapped instrument, and there were 105,719 of them at the last mapping run. The feed writes the whole hash, so subscribing means receiving every update for all of them in order to use a handful. An `HMGET` of twenty instruments against a local Redis was measured at 0.099 milliseconds, so reading once a second for as many instruments as the engine could plausibly have open parents on costs a fraction of a millisecond a second.

Polling also gives the tick a property that a subscription does not: every parent watching one instrument is handed exactly the same quote object, so two parents cannot act on two different pictures of the same moment, and a scenario can be replayed offline against a quote that never existed.

## Why the tick carries a dictionary of quotes

Ten of the eleven watching types want their own instrument and nothing else, so one quote would have been the simpler signature. The cross-instrument conditional is the reason it is not: it exits a Nifty option when the index crosses a level, precisely because the index does not spike the way an illiquid premium does, and it therefore needs a quote for an instrument the parent never trades.

Making that the special case would have meant a second hook, or a quote the type has to go and read for itself outside the one Redis call. A dictionary keyed by instrument id costs the common case one call to `own_quote` and keeps every type reading its prices from the same place at the same moment.

The second instrument is named in the parent's `watch_instrument_id` parameter. The ticker reads that parameter by name rather than asking the class, because the ticker has to know which instruments to read before it builds the runner, and building a runner for every open parent in order to ask it would undo the saving that reading in one call was for.

## Why a failed tick is logged rather than raised

The ticker is called from the engine's main loop, between reading intents and reading order updates. A type that raises on a tick must not stop that loop, because the loop is also what places new orders and what applies fills to a bracket's exits. One trailing stop failing has to cost that trailing stop and nothing else, which is the same rule the clock ticker follows.
