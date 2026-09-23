# Notes on `unified_broker_interface/utilities/order_engine/bracket.py`

## Why it subclasses the OCO

The second half of a bracket *is* an OCO: a stop and a target on one position, each shrinking as the other fills. What a bracket adds is the entry that creates the position and the arming that follows it.

Inheriting rather than repeating means the double-fill rule exists once. A bracket that had its own copy would eventually get one of the two fixed and not the other, and the one that was missed would be the one that cost money.

The inheritance is one level deep and the base class is a concrete type in its own right, which is the shape `CLAUDE.md` asks for: a shallow base holding what is genuinely identical, with each case's own behaviour visible in its own file.

## Why the exits are armed on the first partial fill

An entry for a hundred that fills ten leaves ten units exposed. Waiting for the other ninety before protecting them is the mistake that makes a bracket worse than placing two orders by hand, because somebody placing them by hand would at least know the position was unprotected.

So the exits are placed for whatever has filled, and grown by modification as more fills arrive. The Atlas states this directly, and it is the difference between a bracket that protects a position and one that protects a position it expects to have.

## Why the entry is cancelled when an exit starts filling

An entry still working while the position is being closed goes on buying into a position the exits have already been sized for, and the difference ends up unprotected. Cancelling the rest of the entry comes before reducing the sibling, because the entry is the leg that can still make the problem larger.

## Why the exits are validated before the entry is sent

`ExitLegs().build` is called in `run` and its result thrown away. That looks wasteful and is not: a bracket whose stop prices are unusable is then refused while there is still nothing at a broker, rather than after the entry has filled and there is a position with no way to protect it.

Building it twice costs nothing — it reads no store — and the alternative is discovering the problem at the worst possible moment.
