# Notes on `unified_broker_interface/utilities/order_engine/twap.py`

## Why it is the freeze slicer's opposite

Both split an order into several. The reason is opposite, and the reason is the whole of the difference.

The freeze slicer splits an order because an exchange will refuse it whole. It sends every slice as fast as the rate budget allows, because the only goal is to get the order in.

A TWAP splits an order an exchange would happily take whole, because taking it whole would move the book against itself. It spends its slices as slowly as it is told to, because the delay is the point.

## Why `started_at` is read from `time.time`

The schedule is reckoned from the same clock the tick reads. That sounds obvious and was got wrong first: the start was taken from `SyntheticOrder.now()`, which returns a datetime for stamping events, while the tick passes a Unix time. The two agree in production and did not in the recording, so the second slice never became due.

The general lesson is worth keeping: a schedule and the thing that checks it must read one clock, not two clocks that happen to agree.

## Why a late slice is sent rather than skipped

The check is "has this slice's moment passed", not "is it exactly this slice's moment". An engine busy for ten seconds sends the slice it owed as soon as it notices, which shortens the gap to the next one rather than dropping one.

Dropping would leave the order short by a slice and nobody would be told. Sending late spreads the order slightly less evenly than asked, which is the smaller error and the visible one.

## Why nothing here watches the price

A slice is sent because its time has come. That is the entire definition of a time-weighted average price order, and the moment it starts looking at the book it becomes one of the types in the next stage.
