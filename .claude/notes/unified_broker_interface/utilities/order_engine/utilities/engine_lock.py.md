# Notes on `unified_broker_interface/utilities/order_engine/engine_lock.py`

## What the lock is actually guarding against

Not a contended race between many processes. The realistic failure is one person, or one systemd unit enabled twice, starting a second engine while the first is running. Redis consumer groups would hand the two engines different entries, so most of the time they would each place a share of the orders and nothing would look wrong. The damage appears at a restart, when pending entries are redelivered and both engines can be given the same one, and a duplicate order at a live broker is money.

So the lock is a plain `SET NX EX`, taken before anything else is built, with an engine that cannot take it exiting rather than waiting. There is no queue to join: a second engine is a mistake, and the right response to a mistake is to stop loudly.

## Why the expiry is short and refreshed

Thirty seconds, refreshed every ten. An engine killed with SIGKILL cannot release the key, and a lock without an expiry would then keep its replacement out until a person noticed and deleted it by hand — during market hours, that is order entry down.

Thirty seconds is comfortably longer than the ten-second refresh, so an engine busy with a slow broker call does not lose its own lock, and short enough that a replacement starts before anyone has finished reading the alert.

## Why losing the lock stops the engine rather than retaking it

`refresh` returning False means another process now holds the key. The engine could take it back, and that would be wrong: the other process is placing orders, and two engines is the one thing the lock exists to prevent. Stopping is the only safe move, and the exit code is 1 rather than 2 so systemd restarts it after fifteen seconds — by which time the other engine has either settled as the owner, in which case this one exits again, or gone, in which case this one takes over.
