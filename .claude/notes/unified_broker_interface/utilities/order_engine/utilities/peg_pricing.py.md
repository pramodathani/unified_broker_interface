# Notes on `unified_broker_interface/utilities/order_engine/utilities/peg_pricing.py`

## Why it copies the peg type's rules

The three references, the offset moved away from filling and the rounding onto the passive side are those of `peg.py`, so the `peg` preset sends what today's type sends; the offline scenarios `a_plan_peg_*` send the same requests at the same prices as the `a_peg_*` ones. The cap moved out into `CapModifier`, because a cap is useful on any pricing, not only on a peg.

## What it did not do at first (now done; see "carry_on" below and the 2026-10-05 section)

Today's peg re-anchors its offset when the caller changes the order's price, so it follows the market from the caller's price. A plan order has no `on_leg_modified` yet, so the next tick moves a hand-moved plan peg back to its reference. The trailing stop has the same gap since stage 2c.

## `follows` and `within_body_price` (stage 5c, 2026-10-01)

Today's accumulation prices each purchase at the bid when it is sent, no higher than the caller's limit, at the limit when there is no bid, and never moves it. Rather than a new pricing for that one type, the peg gained two settings: `follows: false` makes `moves` false, and `within_body_price` holds the price at the body's limit. The offline scenarios `a_plan_accumulation_*` place at the same prices as `an_accumulation_*`.

## A caller's changes (added 2026-10-02)

A caller's price is kept as `offset_ticks` in the pricing's memory rather than by changing the pricing object, because the pricing is rebuilt from the caller's plan on every event and only memory survives a restart. `wanted_price` keeps its two-argument form for the example programs and takes the offset as an optional third argument. The offset is rounded to whole ticks, as today's peg rounds it.

## Stale quotes (2026-10-05)

The group 6 walkthrough found every moving pricing acting on a quote marked `stale`: a peg followed a stale bid, a chaser crossed to a stale offer of 1005, an underlying peg moved on a stale index. The quote combiner marks a quote stale when its broker has gone silent and no healthy backup exists, so its price may be minutes old. This pricing now treats a stale quote as no quote, as `LimitMarketableCondition` always did: it neither places from it nor moves on it, and the next fresh quote moves the order as usual.

## Offset after a caller's change (2026-10-05)

`carry_on` turns the distance from the reference into whole ticks with `ROUND_FLOOR`. The default half-to-even rounding turned a mid peg's 1.5 ticks into 2, so a caller who moved a buy to 1000.00 under a mid of 1000.075 saw it re-priced to 999.95 on the same tick. Flooring always reproduces the caller's price after the passive rounding, on both sides.

## Refusing an empty book (2026-10-06)

`on_empty_book: refuse` exists for `marketable_limit`, whose market order must fail rather than wait when nobody is on the other side. A new pricing class was considered and rejected: a peg on the opposite touch, offset towards the market, already prices and follows exactly as a marketable limit should, so the only missing behaviour was what to do when no price can be made. The pricing interface has no way to refuse, only to return no price, so `empty_book_refusal` gives the reason and `OrderPart.order` ends the part as refused with it, the same way the post-only guard does. The plan then answers 409 with that reason when nothing else of it was placed.

A missing quote and a stale one are refused too, not only an empty side. Both mean the engine cannot see who is on the other side, and a market order that waited for them would wait for an unknown time, which is what the user's rule was meant to prevent. The refusal is asked only when the order is first sent: once it rests, a tick with an empty side simply leaves it where it is, and the lifetime cancels it when its time is up.

## The cost guard (2026-10-07)

`maximum_cost_bps` was added as option B of stage 4 of the execution cost plan. It lives on the peg rather than in a separate class because the peg is where a marketable limit is priced and where the existing `on_empty_book` refusal already sits, so `OrderPart.order` asks the peg for one more refusal in the same place, after a price has been made and before anything is sent.

The estimate walks the whole quantity, although the marketable limit is only `buffer_ticks` past the touch and would rest what the first levels cannot fill. That makes the guard cautious; it was preferred to an estimate of only the part that would fill at once, which would let an order that is mostly unfilled through as cheap.

An order bigger than the visible book is refused rather than estimated with the square-root model, because on the order path there are no daily volatility and volume figures without a database read, and the model's coefficient is not fitted yet.

With one side of the book empty the guard says nothing: the empty-book refusal handles the side the order needs, and an empty own side leaves no mid-price to measure from.

`described` shows `maximum_cost_bps` only when it is set, so every dry run and recording of a peg without it is unchanged.
