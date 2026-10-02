# limit_marketable_condition.py

## Why the held terms are written into the trigger's memory (2026-10-01)

`bin/unified/orders/virtual_book` runs as its own process and reads parents from the engine's cache; it cannot run the plan reader. Writing the instrument, side, price and quantity into the trigger's memory when the plan is placed gives it everything it needs from the part record alone, the same four fields it reads from a `virtual_limit` parent's body.

## Why the order must be priced at the body's own limit

The condition compares the other side with the body's price, and the virtual book estimates a resting order at that price. A pricing of the order's own, such as a peg, would send a different price from the one held and estimated, so the reader refuses it as `held_at_the_body_price`.

## Side

The held side is the body's `transaction_type`, while `is_met` reads the sending side. They are the same for the `virtual_limit` preset. With `side: protect` they would differ and the queue estimate would be for the wrong side; nothing refuses that yet, since no preset does it.

## Changing a held order (2026-10-02)

`PlanOrder.modify_held` changes the held terms in this condition's memory, beside the order's part record, so the virtual book sees new terms and starts its estimate again.
