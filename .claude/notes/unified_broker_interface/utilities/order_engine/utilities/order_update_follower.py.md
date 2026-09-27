# Notes on `unified_broker_interface/utilities/order_engine/utilities/order_update_follower.py`

## Why the engine reads the unified stream and not the brokers'

`bin/unified/orders/websocket_order_details` already collects every broker's order updates into `unified:order-updates:stream`, normalised onto one contract. The engine reads that rather than the ten broker streams behind it.

The gain is that adding a broker teaches the engine nothing. A new broker's updates appear on the unified stream in the same shape as everyone else's, and the engine's own code does not change. It also means the engine learns about a fill at the same moment, and from the same words, as everything else in the system, so a disagreement between what the engine thinks and what `GET /api/orders/details` reports cannot come from two different readings of the same event.

## Why both streams are read in one call

`XREADGROUP` takes several streams at once, so the intents and the order updates are read together under one group. Two loops, or a second thread, would mean two things touching the same parents and a lock around them; one loop means neither can starve the other and there is nothing to lock.

The group starts at different places on the two. On the intents it starts at the beginning, because an intent written while the engine was down is an order somebody is still owed an answer for. On the order updates it starts at the end, because the retained history is tens of thousands of updates about orders placed before this engine existed. A restart resumes from the group's own position either way.

## Why both streams are created if missing

An earlier version created only the intent stream, on the reasoning that something else owns the order-update stream and conjuring an empty one would hide a misconfiguration.

That was wrong in a way worth recording. `XGROUP CREATE` without `MKSTREAM` raises when the key does not exist, and that raise happens inside the engine's retry loop, so an engine started before `websocket_order_details` had ever run would fail and retry for ever over a stream that was merely empty. A crash loop is a worse diagnostic than an empty stream, and it stops the engine placing orders it could perfectly well place.

## Why an update that changes nothing is dropped

A broker's websocket repeats an order's state freely, and a poller re-reads the book every second. Recording every repeat would fill `unified.synthetic_order_events` with rows saying nothing happened, and the table's one demanding reader is recovery, which scans the whole day on every start. Keeping only real changes is what keeps that scan quick enough to do before placing anything.

## Why a failed update is acknowledged rather than retried

An update that cannot be applied is logged and acknowledged. Redelivering it would block every update behind it, and the cost of losing one is bounded: the broker's own order book is read at the next start, and it is the authority anyway. Accuracy until then, rather than correctness, is what is at stake.

## Why an update for an unknown order is held rather than dropped

An update used to be dropped the moment `unified:orders:children` named no parent for it. In a single-threaded engine that was safe: the engine saved a leg's broker order id before it read the next entry from either stream, so no update could arrive for a leg it had placed but not yet recorded.

Broker lanes break that ordering. A worker thread sends an order and waits for the answer while the main loop keeps reading the order-update stream, so a fast fill can be read before the worker has saved the order id. Dropping it would lose the fill for good, and a bracket whose entry fill was lost never places its stop.

So an unknown update is held in `EarlyUpdates` for up to 30 seconds. After every batch the engine looks up all held orders with one `HMGET` and applies the ones that are now known, in the order they arrived, so a partial fill held before a full one is applied first. Thirty seconds is far longer than any broker call, whose timeout is 10 seconds, and an update still unknown after that belongs to an order placed somewhere else. The area holds at most 10,000 updates, dropping the oldest, so a flood of updates for orders placed from a broker's own app cannot grow it without bound. The lookup is skipped entirely when nothing is held.

This was fixed on the single-threaded engine before the lanes were built, so the two recorded checks show it working on its own.
