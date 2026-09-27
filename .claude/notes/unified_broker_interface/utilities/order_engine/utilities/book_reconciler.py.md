# Notes on `unified_broker_interface/utilities/order_engine/utilities/book_reconciler.py`

## Why it exists

The engine learned about its orders only from `unified:order-updates:stream`, which only the order websockets feed. In the live retest on 27 September 2026, Flattrade had no order socket service running and INDmoney's socket missed a cancel, so two parents stayed `cancelling` although both orders were cancelled at the broker. The REST pollers keep every broker's whole book in `<broker>:orders:orders` anyway, so the engine can read the truth there without asking a broker anything.

## Why it only moves legs forward

A poll can be older than a socket message about the same order. If the reconciler applied whatever the book said, a book still showing `OPEN` would move a leg the socket had already filled back to `acknowledged`. Taking only a finished status, or a larger filled quantity, means a stale book can never undo what the socket said. A leg's state can never go backwards in the broker's own life either, so nothing real is lost.

## Why it goes through the follower rather than changing legs itself

The follower already decides what an update means, records it, tells the risk gates about fills and hands the change to the order type. Building an update shaped like a stream entry and handing it to the same `follow` keeps one path for every change, so a reconciled fill arms a bracket's exits exactly as a socket fill does. The change runs on the parent's owning worker, and `follow` reads the parent again there, so a socket update and a reconciled one for the same change cannot both apply.

## Cost

One pass is two Redis round trips: an `HMGET` of the open parents and one pipeline of `HGET`s into the books. No broker is contacted. The interval defaults to 5 seconds because the pollers themselves poll every half second to five seconds, so checking more often finds little extra.
