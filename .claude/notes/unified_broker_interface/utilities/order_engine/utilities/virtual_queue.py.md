# Notes on `unified_broker_interface/utilities/order_engine/utilities/virtual_queue.py`

## What it is for

It is the arithmetic of the synthetic limit order book, designed on 2026-09-23. Several brokers cap the number of orders a day, and a limit order resting at the exchange that never fills still spends one. So a `virtual_limit` order is held by the engine and sent only when the opposite touch reaches its price, which fills at once. That release rule gives up queue position, and this class measures what that costs: the fills a resting order would have had while the held one waited.

The estimate deliberately does not decide when to send the real order. Reaching the front of a virtual queue does not put a real order at the front of the real one, because sending it then joins behind everyone who arrived after the virtual order's time. Only a counterparty on the other side at the order's price can produce the fill, which is why the release rule watches the opposite touch.

## The assumptions, each a known source of error

- **All the volume between two quotes traded at the last price.** A single volume jump can hide trades at several prices. With the last price equal to the order's price the whole jump is counted there; with it elsewhere, none is. Brokers send snapshots, at Zerodha about one a second per instrument (not measured here), so on a busy instrument this over- or under-counts.
- **Cancellations are spread evenly through the level.** Nobody can see where a cancelled order stood, so the queue ahead shrinks by its share of the level. Real queues are not uniform: orders at the back are more likely to be pulled, so this probably shortens the queue ahead too fast.
- **The order changes nothing.** The held order is not in the real book, so the estimate assumes nobody would have behaved differently had it been. For an order large beside the visible depth that is wrong, and a large order would have been seen and traded against.
- **Several held orders at one price do not see each other.** Each has its own estimate and each assumes it alone joined the queue.
- **Five levels.** A price beyond the fifth visible level has no known place (`ahead` is None) until it comes into view, and is not filled by trades at its price while unknown. A trade through it still fills it, because that can only happen after every order at the price is gone.
- **An empty level between two shown levels is empty.** The unified quote layer drops empty levels, so a price that falls between two shown levels has nobody resting there.

## Why the baseline is retaken so often

A quote is only compared with the previous one when both came from the same broker, in the same session, with volume that did not go down. The unified layer can switch the owning broker (backups take over after 45 seconds of silence), and two brokers' volume counters need not agree, so the first quote from a new owner only sets a baseline. Volume going down means a new session, whose queue is joined again from the back, since day orders do not survive the night. A stale quote is ignored altogether. An estimate read back from Redis takes its next quote as a baseline too, because whatever traded while nothing was reading cannot be told apart from trading at its price.

## Why `queue_filled` and `filled` are separate

When the opposite touch reaches the price, the engine sends the real order and it fills at once. That is not a fill the queue gave, so it is recorded as `touched_at` and never added to `queue_filled`. For a real order, `queue_filled` at the moment of release is the missed fill. For a paper order, `filled` (the queue's fill, or the whole order once touched) is what it is filled with.

## Prices are compared at four places

Prices are quantized to four decimal places before comparison, because the unified quote layer writes two places for most instruments and four for currency, and `98`, `98.0` and `98.00` must be the same level.
