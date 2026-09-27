# Notes on `unified_broker_interface/utilities/order_engine/utilities/virtual_book.py`

## Why a separate process

The queue estimate needs every quote for the held order's instrument, not the one snapshot a second `PriceTicker` reads, and every quote arrives on `unified:quotes:stream`, which carries all of about 112,400 instruments. Decoding that stream on the order engine's own thread would slow every intent and every fill the engine handles. So `bin/unified/orders/virtual_book` decodes it in its own process and hands the engine a small hash to read.

## Why a plain `XREAD` instead of a consumer group

The plan first said a consumer group. A consumer group keeps every entry it delivers in a pending list until acknowledged, and replays the unacknowledged ones after a restart. Neither helps: old quotes cannot improve an estimate, and replaying them after an estimate has already been rebased would count them twice. Reading from `$` and rebasing every estimate after a gap is simpler and more honest about what was missed.

## Why every quote is decoded

The quote is JSON in one field, and the instrument id is inside it, so filtering before decoding would mean matching on the raw text. That was judged not worth the fragility while nobody knows the stream's real rate at the market open with Zerodha's full feed; see the known issue about the unified quote layer's size. If decoding turns out to be the bottleneck, matching the instrument id's text before `json.loads` is the first thing to try.

## Why a fired order's estimate is kept

When the engine sends the real order it reads the estimate to record the missed fill. The book stops updating an estimate once its parent has a leg or a `triggered_at`, but leaves it in the hash until the parent is no longer open, so the engine never reads an estimate that has vanished between the tick that fired and the write that records it.

## Why a changed held order starts a new estimate

A held order changed through `PUT /api/orders/modify` keeps its body and gains `held_price` and `held_quantity`. `held_terms` reads those first. When they differ from the estimate being kept, `refresh` starts a fresh one, as a changed price at the exchange loses its place in the queue. A reduced quantity at an exchange keeps its place, but restarting on any change is the cautious reading, and keeps one rule.
