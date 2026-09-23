# `legged_spread.py`

## Why the first candidate is the one that gets worked

The order of the two legs is the caller's and it carries two separate meanings, both load-bearing.

It should be the **less liquid** leg, because that is the one that needs a passive limit and patience. Working the liquid leg and then chasing the illiquid one is backwards: the leg left exposed would be the one that is hard to unwind, which is the worst possible outcome of a partial spread.

For Indian futures and options margin it should also be the leg being **bought**. Buying the hedge before selling the short leg gets the spread's margin benefit; the other order briefly demands the full margin for a naked short and can be refused for it, which leaves the spread half on for a reason that has nothing to do with the market.

Those two usually agree, because the hedge is usually the far strike. Where they disagree, the margin rule wins, because a refused order is a worse failure than a slow fill.

## Why the second leg goes out on the first partial fill

Waiting for the worked leg to fill completely would leave the part that has filled one-legged for as long as the rest takes, which on an illiquid strike can be the rest of the afternoon. So the second leg is sized to what has actually filled and sent immediately, and `hedged_quantity` records what has been covered so that a later fill on the same leg sends only the difference.

## Legging risk, which is not solved

Only an exchange's own multi-leg order can guarantee both legs at a net price, and the Indian exchanges' spread products are not reachable through these brokers' APIs. Between the first leg filling and the second, the market can move, and the position can end up one-legged at a net nobody wanted.

The class docstring says so. What is done about it is the choice of which leg to work, which puts the exposure on the leg that can be dealt with quickly rather than the one that cannot.

## What the offline scenario caught

Not a bug in this file: the first version of the scenario put ten units of `reliance_future` on the second leg, and the future's lot size is five hundred, so the leg was refused with "quantity must be a whole number of lots of 500". That is `PlaceOrderRequest` doing its job on an order the engine built, which is the property `concrete_order` was written for — a number the engine works out faces every check a caller's own number faces.
