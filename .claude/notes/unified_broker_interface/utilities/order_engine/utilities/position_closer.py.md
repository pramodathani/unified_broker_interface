# Notes on `unified_broker_interface/utilities/order_engine/utilities/position_closer.py`

## Why it was taken out of `SquareOff`

`square_off` and `close_on_trigger` both close positions they did not open, and both must cancel the resting orders first. The four methods that did this (`open_positions`, `resting_orders`, `cancel_resting` and `closing_order`) moved here unchanged apart from taking the product, the instruments and the cancel reason as arguments. The square-off's recorded scenarios did not change.

## Why it holds the order type rather than the placement

Every cancel goes through the type's `cancel_outside_order` and every read through its placement, so the cancels are recorded on the type's own parent and pass its rate budget. Holding the type keeps that true for every type that uses the closer.

## Why `closing_order` rounds with the closed instrument's own tick size

`SquareOff.closing_order` rounded every closing price with the parent's own tick size, which was only right for the parent's own instrument. A square-off of several instruments with different ticks, or a hedge in a future whose tick is 0.10 against a stock's 0.05, could be priced off-tick and refused. `closing_order` now works out the agreed tick size of the instrument it is closing from that instrument's handles. The recorded scenarios did not change, because they close instruments whose tick matches the parent's.
