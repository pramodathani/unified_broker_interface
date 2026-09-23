# `discretionary.py`

## Why the visible order is reduced before the taking order is sent

Both orders can fill. If the taking order goes first and the visible one is reduced afterwards, a fast market fills both and the account ends up with twice the position it asked for. Reducing first makes the window one request wide rather than two requests wide, which is as small as it can be made without an exchange primitive that does not exist.

This is the same rule `oco`, `bracket` and `two_sided_breakout` follow, and the same bug the Atlas names as the recurring one in every linked pair.

When the whole remaining quantity is being taken, the visible order is cancelled rather than reduced, because reducing an order to zero is not something a broker accepts.

## Why the taking price is capped at the discretion

The taking order is priced a couple of ticks past the touch so that it clears whatever is resting there rather than joining the queue behind it. When the touch is already at the edge of the discretion, those two ticks are two ticks past what the caller agreed to.

The first run of the offline scenarios showed it exactly: a discretion of 0.25 on a visible price of 1000.00, an offer arriving at 1000.20, and an order sent at 1000.30. The cap in `within_discretion` holds it at 1000.25. The order may then not clear the whole level, which is the correct trade-off — the caller stated a limit and the limit is what they get.

## Why the discretion quantity defaults to everything

The order was going to trade at the visible price eventually, so trading now at a price inside the discretion is simply better than waiting. Taking a slice and leaving the rest showing is the more specialised behaviour: it is for somebody working a position who wants to keep a visible bid in the book for its own sake.
