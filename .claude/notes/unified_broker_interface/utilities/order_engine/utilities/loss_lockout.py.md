# Notes on `unified_broker_interface/utilities/order_engine/utilities/loss_lockout.py`

## Why it is off by default, and why the engine complains about that

A daily loss limit is the gate that matters most, and it is the one nobody but the person trading can set. Too low and it stops an ordinary day at the first drawdown; too high and it is theatre that makes everyone feel safer without changing anything. Guessing a number would be worse than having none, because a guessed limit looks like a decision.

So it is off at zero, which is the default, and `bin/unified/orders/order_engine` logs a warning at startup saying that nothing stops it placing orders on a losing day. The warning is the point: an operator who reads it either sets a limit or has decided not to, and both are better than not knowing.

## Why unrealized loss counts

Realized plus unrealized. A position held at a large loss has lost the money whether or not it has been closed, and a lockout that counted only realized loss would let a strategy average down indefinitely, closing nothing and therefore never tripping.

## Why an unreadable funds document does not lock trading out

The gate fails open, deliberately, and that is the one choice here a reader might disagree with.

Redis being briefly unreadable is common — a restart, a brief network fault, the store still loading its dataset after a reboot, which `docs/contributing/pitfalls.md` already records as having taken seven services down. A gate that turned every such moment into a halt would be its own outage, and would do it at exactly the times the rest of the system is already struggling.

The failure is logged at warning so it is visible rather than silent. The position taken is that a loss limit protects against a strategy behaving badly, not against the infrastructure failing, and the second needs a different answer.

## Why the check happens before the parent is created

`RiskGates.check_before_accepting` runs before the intent becomes a parent, so an order refused for a locked-out day leaves nothing in the event log and nothing in the open set. Whether the day may trade at all does not depend on which broker the order would go to, so there is nothing to be gained by working it out first.
