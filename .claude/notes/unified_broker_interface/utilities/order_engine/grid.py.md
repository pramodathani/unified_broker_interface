# `grid.py`

## The inventory cap, which took a rewrite

The first version checked the cap before placing the replacement rung, and would have shipped doing nothing at all. A filled buy is replaced by a sell one step above it, and a sell always makes a long position smaller, so the check could never refuse anything. The offline scenario with a deliberately tiny cap placed exactly the same orders as the one without it, which is what showed it up.

The orders that grow the position are not the replacements. They are the rungs already resting further down the ladder, placed when the grid was set up. In a market that falls all afternoon, each of those fills in turn and the grid is long more at every worse price.

So the cap now cancels. Once the net position reaches `most_inventory`, every resting rung on the side that would make it bigger is cancelled and only the exits are left. The grid goes one-sided until the market comes back, which is the honest behaviour: it stops digging.

## Why `most_inventory` is required rather than defaulted

Every other bound in this package has a sensible default. This one does not, because there is no number that is right for an instrument the engine knows nothing about, and because the failure it prevents is the one failure of this type that loses real money quietly.

A grid without a cap looks correct on every quiet day and is ruinous on the one trending day. Making the caller state the number is the only way to be sure somebody has thought about it.

## Why the order's quantity is one rung rather than the whole grid

A grid has no whole. It is a standing arrangement that may trade the same rung a dozen times in a day, so there is no total for the quantity on the request to mean. It is therefore the size of each individual rung, which is the only reading that stays true however long the grid runs.
