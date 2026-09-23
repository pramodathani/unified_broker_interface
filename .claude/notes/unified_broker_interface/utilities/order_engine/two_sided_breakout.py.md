# Notes on `unified_broker_interface/utilities/order_engine/two_sided_breakout.py`

## Why the other side is cancelled rather than reduced

Every other linked type in this package reduces a sibling rather than cancelling it, and this one does the opposite deliberately.

The reduce rule exists because two exits are tranches of one position: when one takes part of it, the other should cover the rest. The two entries here are not that. They are opposite trades, and only one of them is wanted. Reducing the sell stop by what the buy stop filled would leave a smaller sell stop still sitting there, which on a whipsaw would take the position straight back off and leave the account flat having paid the spread twice.

## Why the exits are built from the entry that filled

`Bracket.arm_exits` takes the side from the caller's `transaction_type`. That field means nothing here: the whole point is that the trade could have gone either way, and the caller does not know which.

So the exits are built against the entry that actually filled, using its own `transaction_type` as recorded when it was sent. A stop given as a price is then applied on the correct side whichever way the break went.

## What it cannot do

A spike through both triggers inside one tick fills both before any cancel can leave the machine. The account is then flat, having paid the spread twice and two lots of charges.

Nothing here prevents that, and the Atlas is clear that nothing could: the exchange offers no order that links two entries. What the engine does is notice immediately and record it, so it is visible rather than discovered later from a statement.
