# `basket.py`

## Why every leg goes to one broker

The first version let the selector choose for each leg, on the reasoning that a basket is several independent orders and spreading them uses the rate budget better. The offline scenario showed what that means in practice: three legs, three brokers.

That is wrong for the reason people send baskets. Margin offsets exist inside one account and nowhere else. An iron condor with two legs at one broker and two at another is charged as four naked positions rather than as a defined-risk strategy, which at best ties up several times the margin and at worst is refused outright for want of it. The same is true of any hedged pair.

So a basket follows the rule the rest of the package follows: every leg of one parent goes to the broker the first one chose.

## Why it is not all-or-nothing and says so

No basket order anywhere is atomic — brokers sell theirs as a convenience too. What this adds over five separate HTTP requests is that the five are one parent: one identifier finds them all, one event log records them in order, and one answer says which got through.

That last part is the part worth having. A four-legged options strategy whose third leg was rejected is not three quarters of a strategy; it is an unhedged short somebody needs to know about immediately. So the answer lists every leg's outcome rather than reducing them to one verdict, the parent's outcome is `partial` when some legs were rejected, and the parent goes to `failed` rather than `working` when any leg's fate is unknown.

## Why the leg order is the caller's

Legs go out in the order given, and that is load-bearing for Indian futures and options margin: buying the hedge before selling the short leg gets the spread's margin benefit, where the other order briefly demands the full margin for a naked short and can be rejected for it.

Sorting the legs by anything — instrument, side, size — would break that silently, so nothing is sorted.
