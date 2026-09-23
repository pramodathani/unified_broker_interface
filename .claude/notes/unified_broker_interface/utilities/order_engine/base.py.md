# Notes on `unified_broker_interface/utilities/order_engine/base.py`

## Why every order reaches a broker through `place_leg`

`place_leg` records the leg, commits, sends, and records the answer. Nothing else in the engine is allowed to call `placement.send`, and that restriction is the whole of the recovery design rather than a style preference.

The `leg_requested` row goes in before the request leaves the machine, so a crash between the two leaves a row saying an order may exist at that broker, with the request exactly as it went out in `detail`. Without that ordering, a crash mid-send leaves no trace at all and the position is discovered only when somebody reads the broker's order book by hand.

`detail` holds the request as a dry run would show it, which is what the orphan matcher compares against the broker's book afterwards. That has to be the request as sent rather than the order as asked for: quantities are converted into the broker's own lots on the way out, so the caller's ten units may be one lot in the book.

## Why `record` writes and applies in one step

`record` writes the event to the database, commits it, and only then applies it to the parent in memory. The parent can therefore never be ahead of the record on disk. If the write fails the parent is left exactly as it was, and the caller decides what that means, rather than the engine believing something happened that was never written down.

## Why `abandon` exists

A refusal raised after `record_received` — an unmapped instrument, no broker able to take the order — would otherwise leave the parent in `received`. That state is not terminal, so the open set keeps it, and recovery would pick it up at every restart for ever with nothing it could do about it.

A refusal means no request was sent, so `rejected` is the honest end, and `abandon` records it. The offline recording covers this directly: the two scenarios where an order is refused after the parent exists both end with an open-parent count of zero.

A parent with nothing recorded yet, such as a dry run's, is left alone. There is nothing to close.

## Why a dry run records nothing at all

`SimpleOrder.run` answers a dry run from `prepare` without creating a parent or writing an event. Nothing happened: no order exists, so there is nothing for recovery to find and nothing for a later reader of the event log to be misled by. A dry run that left a parent behind would be a parent that never finishes.

## Why changing and cancelling take a rate token too

An exchange does not distinguish a placement from a change or a cancel: all three are requests against the same per-second allowance, and SEBI's algorithmic-trading threshold counts them the same way. Until `take_rate_token` existed the budget covered placements only, which was tolerable while no order type changed an order after sending it.

It stops being tolerable the moment a type re-prices. A chaser that walks its limit towards the touch, or a peg that follows the best bid, spends almost its entire request budget on changes and would have been completely invisible to a budget that only watched placements. The same is true of the linked types, which reduce a sibling on every partial fill.

A refusal is recorded against the leg and returns `False` rather than raising. The caller is usually reacting to a fill and has other legs to attend to, and an exception would abandon them. The thing that did not happen is in the event log either way, which is what a later reader needs.

The offline recording covers this with a bracket run behind a budget of three requests a second. The entry and the two exits spend the whole allowance, so the two changes that would have grown the exits from four to ten are refused, and the exits stay at four. The same scenario without the guard sends all five requests.
