# Notes on `unified_broker_interface/utilities/order_engine/utilities/participation_execution.py`

## Why it copies the participation type's rules

The share of traded volume, the `int(traded × percent / 100)` rounding down, the cap of `most_slices` (default 60) and counting from the volume when the order starts are those of `participation.py`, so the `participation` preset sends what today's type sends.

## What is kept in memory and what is derived

`counted_volume` is the one value that cannot be worked out again after a restart, so it lives in the part's `execution_memory` and is saved with the placement's event. How much has gone is read from the part's own legs. `remaining` counts what filled of a finished slice and the whole of a resting one, so the unfilled part of a cancelled slice is sent again by later slices, while a resting slice is never sent twice.

## Why a rejected slice stops it

Today's type would send a fresh slice on every tick after a rejection, which repeats the same rejection, so here a rejected last slice stops the order, as a rejected piece stops an iceberg.

## A quote without volume

When `begin` ran on a quote with no `volume`, `counted_volume` is None, and the first tick that carries a volume starts the count instead of treating the whole day's volume as traded since the start.

## Whole lots (fixed 2026-10-02)

The plan execution never lost quantity, because it reads what it has sent from its legs, but it did not round to lots, so it only sent once a share happened to be whole lots, and across a restart the logged `counted_volume` lost that volume credit. `due_pieces` now rounds the share down to whole lots and leaves `counted_volume` alone when that comes to nothing, using the same lot rule as the fixed type.
