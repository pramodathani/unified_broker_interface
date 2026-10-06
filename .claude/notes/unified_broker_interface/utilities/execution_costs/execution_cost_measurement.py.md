# Notes on `execution_cost_measurement.py`

## Choosing the decision moment

The first leg of a parent is measured from `parent_received`, because that is when the caller decided to trade, so the time a held limit, a conditional order or a slow placement waited counts as delay. That is standard implementation shortfall. Every later leg, such as a stop or a target placed after an entry fills, is measured from its own `leg_requested`, because the engine decided on it then; measuring a stop from its parent's arrival hours earlier would charge it for the whole day's price move.

## `MAXIMUM_QUOTE_AGE_SECONDS = 60`

The unified feed only emits a tick when something changes, so an illiquid strike can go many seconds without one while its book is unchanged. Sixty seconds accepts that, while still treating a feed that had stopped as missing. The quote times are stored, so an analysis can apply a stricter limit later. On 2026-10-05 and 2026-10-06 the decision quote was 0.73 s old at the median and 11.7 s at the oldest.

## `PARENT_LOOKBACK_DAYS = 30`

The event query reads every event of each parent that sent a leg in the days measured, but only rows from up to 30 days before the first day. A parent that carries overnight can send a leg days after it arrived, and its `parent_received` row is needed for its first leg's decision moment. Thirty days is longer than any parent is expected to live and keeps the scan bounded; an older parent's first leg falls back to its own request time.

## Reading in one transaction and rolling back

`measure` opens one connection, runs every read on one cursor and rolls back, so the reads see one snapshot and leave no transaction open.

## Writing

`write` applies the DDL file, deletes the days and inserts the rows in one transaction, so a failed insert leaves the old rows in place. `executemany` is used rather than `COPY` or `execute_values` because a night has hundreds of rows and the stand-in database only needs to understand one form.

## Medians and means

Both are rounded to a hundredth. The median of an even number of figures is the average of two, which had three decimal places before rounding was added.
