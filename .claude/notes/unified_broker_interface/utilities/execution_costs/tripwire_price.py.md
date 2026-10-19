# tripwire_price.py

The allowance is a share of the trigger, not of the floor, because the slip is measured relative to the trigger the stop actually had (`slip_basis_points` in `unified.stop_slippage`). Solving trigger × (1 − q) = floor for the trigger therefore keeps a fill that slips by exactly q at or above the floor; `test_runs.stop_slippage` checks that for four allowances, both sides and brokerage of 20.

The fallback when a segment has fewer than 30 measured stops is the live spread plus two ticks. It was chosen to be cautious without history: a held stop fires on the bid (for a sell) and fills at or a tick or two under it, and the spread covers a book that moves while the order travels. With a spread of 0.20 it gave +0.30 over the floor on 19 October, close to the measured median slip (15.79 bps, 0.28 on a 177 option), well short of the 90th percentile.
