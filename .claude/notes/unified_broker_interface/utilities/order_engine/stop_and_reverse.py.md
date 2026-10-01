# Notes on `unified_broker_interface/utilities/order_engine/stop_and_reverse.py`

## Why it subclasses `CloseOnTrigger`

The plan said `PriceTrigger`. A stop-and-reverse is a close-on-trigger with a second order added: the same cancels first to free margin (which the new side needs even more than an exit does), the same position read, the same product check. Subclassing it leaves only the flip in this file.

## Why the sequential reverse waits for a complete fill

The one-triggers-other order grows its child as the parent fills, which needs `reduce_leg` to resize a resting order. Waiting for the close to complete sends the reverse once, at its full size, with no modifies. The close is a limit two ticks past the touch, so it normally completes at once; a close that stays partly filled leaves the reverse unsent, which is the safe direction to fail in.

## Why the reverse is built with `closing_order` again

Closing a long of 75 is a sell of 75, and opening a short of 75 is also a sell of 75, so the same `PositionCloser.closing_order(instrument, 75)` builds both, priced from the book at the moment each is sent. The doubled method passes twice the quantity.

## Why `reverse_from` is kept per broker

Positions now come one per broker, and each broker's share is closed or doubled at that broker. In sequential mode the reverse for one broker is sent when that broker's close fills, so `reverse_from` maps broker names to the quantity each close was sent for, and a reverse already sent is recognised per broker. `_reverse_quantity` still reads the single string that parents stored before 2026-10-01, so a parent that was waiting across the upgrade can still send its reverse.
