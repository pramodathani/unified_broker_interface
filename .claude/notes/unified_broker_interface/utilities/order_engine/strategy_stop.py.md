# `strategy_stop.py`

## Why no exchange can do this

An iron condor has four legs and no single one of them says whether the trade is working. A stop on the short call is taken out by a move the long call above it has already paid for. The only number that means anything is the total.

No exchange will ever watch a total, because it has no idea which four orders somebody considers one trade. That grouping exists only in the mind of whoever placed them, which is exactly what a parent order is, and that is why this type can only live here.

## Why the exit order is shorts first

Closing a long hedge while its short is still open turns a defined-risk position into a naked one. That matters for the seconds it takes, because a broker looking at the account in that instant sees a margin requirement several times larger, and can refuse the second order — leaving the position stuck in the naked state, which is the opposite of what closing it was for.

So shorts are bought back first and the hedges that were covering them second. Nothing is sorted by instrument or size, because the only ordering that matters is this one.

## Why an incomplete mark does nothing

The total is acted on only when every filled leg could be marked against a live quote. A condor with one leg's quote missing is not a three-legged condor worth acting on: it is a number that happens to be smaller than the truth, and the direction of the error is unknowable.

Closing on that would mean a quote feed hiccup on one strike closing a whole strategy. Waiting a tick costs a second.

## What the mark actually measures

The last traded price, which is roughly what a broker's own position screen shows, not what the position could be closed at. On a wide book those differ and the difference is against you, so a strategy stop set at a loss limit will in practice close somewhat past it.

Marking against the bid and offer instead would be more honest about exit value and would make the number jump around with the spread, which on four illiquid strikes is worse. The class docstring states which one it is so that nobody has to guess.
