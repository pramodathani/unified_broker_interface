# Notes on `unified_broker_interface/utilities/order_engine/utilities/reduce_only.py`

## Why the check sits in `place_leg`

A reduce-only order (the Atlas's G11) must never open or flip a position, whichever type it is and however long after the request its legs go out. `place_leg` is the one method every leg passes through, so checking there covers every type, including a trigger that fires hours later, against the position at the moment of sending. The check runs before `prepare`, so a refused leg costs no broker selection and no rate token. The Redis read for positions happens only for orders marked reduce-only.

## Why the product names are translated

Orders are placed with the request products `CNC`, `MIS` and `NRML`, while the unified positions document spells them `delivery`, `intraday` and `carry` (see the product table in `docs/architecture/contracts.md`). `POSITION_PRODUCTS` translates the order's product so only the position in that product counts. A first draft used `carryforward` for `NRML`, following a docstring in `square_off.py`, and would have found no position for any carry-forward order.

## What it does not count

Other orders still resting are not counted. Two reduce-only orders each smaller than the position can together close more than is held. Counting them would mean reading every broker's open orders on every leg, and the brokers' own order books lag the engine's sends by up to a poll interval, so the sum would still be wrong in exactly the fast case it is meant for.
