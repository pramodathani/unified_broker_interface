# Notes on `unified_broker_interface/utilities/order_engine/utilities/price_reference.py`

## Why thirty-three methods become two fields

The sibling project's `TradeableInstrument` has thirty-three methods that place an order: `buy_at_best_bid_price`, `sell_at_third_best_offer_price`, `buy_at_mid_price`, `sell_at_volume_weighted_average_price`, `reduce_position`, and so on. Read as a list it looks like thirty-three things to implement.

It is not. It is a side, a price reference and a quantity reference crossed with each other, and the cross product is what makes the list long. Sixteen of the methods are the five depth levels on two sides for two sides of the trade; six are the midpoint, the last price and the average price; five are the position ones. Two fields on the place route cover all of them, and a thirty-fourth method somebody thinks of later needs no new code at all.

## The float bug, which is the reason the snapping exists

A quote is built from JSON numbers, so the depth arrives as floats. The second best offer of 1000.10 is `1000.0999999999999`.

Rounding that towards the passive side, which a buy does, floors it to 1000.05. A caller who asked for the second best offer would quietly get the best offer — not a rounding error of a hundredth of a paisa but a different level of the book, one tick away, every time.

So every price read out of the quote is snapped to the nearest tick before anything else happens. That is safe because a price in the depth is a price an exchange already accepted, so it is on a tick boundary by construction and the snapping can only remove noise the feed added.

Values the engine computes are deliberately **not** snapped at that point. A midpoint belongs between two ticks when the spread is one tick wide, and which way it goes is the side's decision, made afterwards.

The bug was found by reading the recorded prices rather than by a check failing: the scenario passed, with the wrong price in it. It is worth remembering that a recording only catches what somebody looks at.

## Why the rounding direction depends on the kind

Everything rounds towards the passive side — a buy down, a sell up — so that an order meant to rest actually rests rather than crossing the spread and paying to take liquidity.

`marketable` is the exception and rounds the other way. It exists to cross, and rounding it passively would be a tick's worth of working against the one thing the caller asked for.

## Why an offset always moves towards filling

`buffer_percent`, `offset_percent` and `offset_ticks` all move the price in the direction that makes the order more likely to fill: up for a buy, down for a sell. That is what somebody means by "the offer plus a tenth of a per cent" — pay a little more to get done.

Making the sign absolute instead, so that plus always meant up, would be defensible arithmetic and a trap: the same reference would mean "pay more" on a buy and "accept less" on a sell only by coincidence of which side it was used on. A negative offset improves the price, which is the one thing the caller can still express.
