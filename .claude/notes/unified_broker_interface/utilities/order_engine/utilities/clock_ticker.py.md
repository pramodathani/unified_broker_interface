# Notes on `unified_broker_interface/utilities/order_engine/utilities/clock_ticker.py`

## Why the clock is the loop rather than a thread

The engine's read of its streams blocks for about a second when nothing arrives. That is already a clock, once a second, and it costs nothing.

A thread would have been the obvious alternative and would have brought the one problem this engine has carefully avoided everywhere else: two things touching the same parent at the same moment. A fill arriving while a square-off is being placed would need a lock around every parent, and a lock held across a broker call is a lock held for three hundred milliseconds. Using the loop means there is still exactly one thing acting on a parent at a time and nothing to lock.

Measured on the live engine: seven ticks in seven seconds.

## Why only some types are read

`WANTS_CLOCK` is False on the base class, so a type has to ask. The ticker looks at the registry first and does nothing at all when no registered type wants a tick, which means an engine running a hundred plain orders and brackets makes no extra Redis read per second.

Without that, every engine would read the open set once a second for ever, to find nothing, in the common case where nothing is waiting for a time.

## Why a tick reads Redis rather than keeping parents in memory

The ticker re-reads the open parents each tick instead of holding them. That is a round trip a second when something is waiting.

Holding them would be faster and would mean two copies of a parent: the ticker's and whatever the follower just wrote after a fill. The types that use the clock are exactly the ones that also react to fills — a `time_stop` has to know how much its entry filled before it can close it — so a stale copy would close the wrong quantity. Reading is the version that cannot be wrong.

## Why a failing parent does not stop the tick

Each parent's tick is wrapped. One order type raising must not stop the others, because the others include a square-off somebody is relying on to be out of the market before the broker does it for them at a price nobody chose.
