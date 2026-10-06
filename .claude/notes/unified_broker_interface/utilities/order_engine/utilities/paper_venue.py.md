# paper_venue.py

## Why a paper order is the whole plan (2026-10-01)

A paper fill trades nothing, so a Then join's child sized by it would be sent for real against a position that does not exist, and a sibling in a Together or Either join would mix real and imagined fills in one parent. Today's type is a single order, so the reader allows paper only at `root`.

## Why it waits on `limit_marketable` alone

The fills come from the virtual book's estimate, which exists only for an order held at its limit. Another trigger, or `limit_marketable` inside an `all` group, would leave the order with no estimate or one that does not describe it.

## Where the fills are counted

The paper fill count lives in the part record as `paper_filled`, recorded with a message so a restart replays it, and `PlanOrder._finish_if_done` adds it to what the legs traded, so a plan filled wholly on paper ends `completed` as today's type does.

## Why the touch walks the book (2026-10-07)

Until 2026-10-07 the other side reaching the price filled the whole remaining quantity at the limit, because `VirtualQueue.filled()` counts the rest of the order as filled once `touched_at` is set. That is right for its own purpose: for a real held order, the touch is when the engine sends it. For a paper order it overstated what would fill: a paper buy of 5,000 would fill entirely when 100 were offered at its price. It was the first part of stage 4 of the execution cost plan (see `docs/architecture/execution-costs.md`) because paper orders never reach a broker, so the change carries no risk to live orders.

Now the touch is walked once, against the quote of the tick that saw it, with `BookWalk` over the levels at or better than the limit, and stored in the part record as `paper_touch`. Walking it once matters: the next tick's quote still shows the same offers, because a paper order never took them, so walking every tick would fill the same liquidity again and again. After the touch, the rest fills only from the queue, at the limit.

`VirtualQueue` itself is unchanged, because the real virtual limit depends on `filled` meaning "would be sent now".

The total filled is `min(quantity, queue_filled + touch quantity)`. After the touch, trades at the price that the queue estimate counts may in reality have been the same liquidity the touch took, so this can still be slightly generous; it was judged the simplest rule that removes the large overstatement.

The fills carry `average_price` on the `paper_filled` event (a column the event log already had), with the touch's units at their walked prices and the rest at the limit, and the order's price stays in `price`.
