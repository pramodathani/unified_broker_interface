# Notes on `unified_broker_interface/utilities/order_engine/utilities/either_part.py`

## Why `reduce` sets each child to the budget less its siblings' fills

A stop and a target of 10 protect one position. When the target has filled 7, the stop should cover the 3 still held. Setting each child's target to `budget - siblings_filled` expresses exactly that from the fills as they are now, and `OrderPart.set_target` turns it into a resting quantity of what the child has filled plus what is still wanted. When nothing is left, the child is cancelled. Because it is recomputed on every settle, there is no per-pair bookkeeping of the kind `OneCancelsOther.take_fill_off` needs.

## Why `reduce` needs single orders as children

The budget is shared between orders that each close part of one position. A Then join or another Either as a child has no single resting quantity to set, so the reader refuses it with `reduce_needs_orders`.

## Why `cancel` stops waiting children too

For two entries that are different trades, the first fill decides which trade is on. A sibling still waiting for its trigger must not fire later, so it is marked done as `cancelled` even though it never placed anything.

## Why `cancel_before_send` sends only once every cancel was accepted

A hidden stop whose trigger holds must not exit while its native backstop can still fill, or both could fill and the position would be reversed. The plan order asks the join to cancel the siblings first and sends only when every cancel was accepted; otherwise the waiting order tries again on the next tick. Today's hidden stop ignores the result of cancelling its backstop, which is one of the suspected bugs listed in the design document.

## Why a child's budget defaults to the body's quantity

An Either at the root, such as an OCO, has no parent join to set a target, so its children share the caller's quantity: the position being protected.

## A caller's changes (added 2026-10-02)

`take_caller_change` puts a caller's cut on the join's shared budget rather than on one child, so every child of a `reduce` join comes down by the same amount and the next settle cannot grow the cut exit back. It mirrors today's OCO, where cutting one exit brings the other down to match. Under the `cancel` rule the children are different trades, so `PlanOrder.on_leg_modified` only routes a change here for `reduce`.
