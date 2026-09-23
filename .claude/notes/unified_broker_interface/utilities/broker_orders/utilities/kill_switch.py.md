# Notes on `unified_broker_interface/utilities/broker_orders/utilities/kill_switch.py`

## Why this decides and does not act

The class works out what has to be cancelled and what has to be closed, and returns lists. The blueprint reads Redis and sends.

Two reasons. The rule recorded in `.claude/notes/unified_broker_interface/blueprints/orders.py.md` is that every Redis read the order routes make is in one module, and a panic button is no reason to break it — if anything it is the route whose cost most needs to be readable. And a decision separated from its I/O can be checked offline against order books and positions that never existed, which for something that unwinds an account is worth more than the separation costs.

## The ordering, which is the only thing here that really matters

Cancel everything, wait until the brokers agree the orders are gone, then close.

A stop or a target still resting at the exchange when its position is closed will fill afterwards and open a new position in the opposite direction. An attempt to go flat then leaves the account short when it was long, unattended, with whoever pressed the button believing it is flat. That is worse than not pressing it.

The waiting is the part that is easy to leave out, because sending the cancels feels like cancelling. `still_open` exists so the caller can keep asking, and the route reports what was still live when it gave up rather than claiming success.

## Why an unrecognised status is treated as live

`is_finished` lists the four statuses that mean a broker can do nothing more. Anything else, including a status nobody has mapped, is cancelled.

A status the shared vocabulary does not recognise is far more likely to be a live order at a broker that invented a spelling than a finished one — `docs/architecture/contracts.md` says unrecognised statuses are passed through uppercased rather than forced into the vocabulary, precisely so this is visible. Cancelling something already finished costs a refusal that is reported and ignored. Not cancelling something live costs a position.

## Why positions come from each broker rather than the unified document

`GET /api/portfolio/positions` merges a position across brokers, deliberately: one row when they share an instrument and a product. That is the right answer for somebody looking at what they hold, and the wrong one here, because a closing order has to go to the broker that actually holds it.

Only `NET` positions are closed. Zerodha and Wisdom Capital report a `DAY` basis as well, and closing on both would trade the same holding twice.
