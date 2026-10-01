# Notes on `unified_broker_interface/utilities/order_engine/utilities/position_closer.py`

## Why it was taken out of `SquareOff`

`square_off` and `close_on_trigger` both close positions they did not open, and both must cancel the resting orders first. The four methods that did this (`open_positions`, `resting_orders`, `cancel_resting` and `closing_order`) moved here unchanged apart from taking the product, the instruments and the cancel reason as arguments. The square-off's recorded scenarios did not change.

## Why it holds the order type rather than the placement

Every cancel goes through the type's `cancel_outside_order` and every read through its placement, so the cancels are recorded on the type's own parent and pass its rate budget. Holding the type keeps that true for every type that uses the closer.

## Why `closing_order` rounds with the closed instrument's own tick size

`SquareOff.closing_order` rounded every closing price with the parent's own tick size, which was only right for the parent's own instrument. A square-off of several instruments with different ticks, or a hedge in a future whose tick is 0.10 against a stock's 0.05, could be priced off-tick and refused. `closing_order` now works out the agreed tick size of the instrument it is closing from that instrument's handles. The recorded scenarios did not change, because they close instruments whose tick matches the parent's.

## Why positions are read from each broker, not from the unified document

Until 2026-10-01, `open_positions` read `unified:portfolio:positions`, which `bin/unified/portfolio/positions` builds by merging a position across brokers into one row per instrument and product. The types then sent every closing order to one broker, `chosen_broker()`. A position of 5 at Flattrade and 3 at Zerodha was therefore "closed" with one sell of 8 at Flattrade, which left Flattrade 3 short and Zerodha still 3 long. The offline scenario `a_square_off_closes_a_position_split_across_brokers_at_each_broker` recorded exactly that against the old code before the fix.

`open_positions` now reads each broker's `<broker>:portfolio:positions` through `KillSwitch.positions_to_close`, the same reading `POST /api/orders/flatten` does, and returns the broker with each position. That reading has been used live by flatten, which is why it was reused instead of writing a second decoder. The broker's product code is translated to the positions document's words with `POSITION_PRODUCTS` from `reduce_only.py`, since the callers filter on `intraday`, `delivery` and `carry`.

The instrument is found from the broker's token in `unified:broker_tokens`, as flatten's `_instrument_for_broker_token` does, and only when the token names exactly one instrument. Resolving it the other way, from the instrument's order handles to each broker's token, was considered and rejected because it would differ from flatten's proven path. A position whose token cannot be resolved, such as a Groww cash position, which carries no token, cannot be priced or placed through the engine; it is returned with an instrument of None when the caller asked for every instrument, so square off can count it as not closed, and left out otherwise.
