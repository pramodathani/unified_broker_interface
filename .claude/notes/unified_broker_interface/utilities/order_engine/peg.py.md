# `peg.py`

## Why the cap holds the order rather than cancelling it

A peg whose reference runs past its cap has two sensible answers: stop following and rest at the cap, or stop altogether. Resting at the cap is the right one, because the cap is a statement about what the trade is worth and the reference is only a statement about where the crowd currently is. An order resting at the most a caller will pay is exactly a limit order, which is what they asked for, and if the market comes back it fills.

Cancelling would also mean the order has to be re-placed when the reference comes back inside the cap, which loses the queue position a second time and turns one order into an unbounded number of them over a volatile hour.

## Why the throttle is not a parameter of this class

The Atlas's recipe for a peg carries its own `min_move` and `throttle`, and the first draft of this class had both. They were taken out and moved into `reprice_leg`, because every re-pricing type needs exactly the same two protections and a per-type copy is a per-type opportunity to forget one.

The minimum move became the unconditional refusal to send a change that changes nothing, which needs no parameter at all: a move to where the order already is is never what anybody meant. The time throttle became `RepricingThrottle`, configured once for the whole engine, because it is a property of how much request budget the account has rather than of what this particular peg is trying to do.

## Why the reference names are not the Atlas's

The Atlas calls them peg-to-primary, peg-to-midpoint and peg-to-market, which are the names the American venues use and which are close to meaningless without that background. "Peg to market" in particular means the *opposite* side's touch, which reads backwards to anybody who has not met the term before.

`own_touch`, `mid` and `opposite_touch` say the same three things in words that can be worked out from the words. The trade-off is that somebody arriving from an Interactive Brokers manual has to translate once, which is the smaller cost.
