# scale_out_exits_part.py

## Why only the exits are kept whole (2026-10-02)

The entry of a scale-out is an ordinary order that a Then join already handles, as `bracket` does, and keeping it outside the part lets it carry any other preset, such as market if touched. What no join expresses is the exits: targets that are tranches of one position, and a stop that shrinks only when a target fills. So `scale_out` is a join preset of the entry and `scale_out_exits`, and the exits are the kept-whole part. `NEEDS_THEN` makes the reader refuse the exits anywhere but under a Then join.

## One rule sizes the stop

`fit_stop` sizes the stop to the entry's fill less what the targets have taken, and only modifies it when that differs. The Then join calls `set_target` on every update before it settles the child, so a target's partial fill is taken off the stop once whichever runs first, and the second fill of the same target takes off only its new part, as today's scenario checks. Today's `grow_exits` sizes the stop to the entry's fill less the stop's own fill, which forgets what the targets took; the part does not repeat that.

## The stop filling

Today's type takes the stop's fill off every target, as a bracket's OCO rule does, which over-cuts tranches that together add up to the position. The part cuts the resting targets furthest first, down to what is still held after the stop's fill.

## Cancels asked once

A cancel's confirmation settles the plan again, and while another order's cancel is still unconfirmed the exits would ask for it again. `WholePart.cancel_once` keeps the leg ids already asked for in memory.

## Testing the move to breakeven

The engine refuses to give a trigger price to an order the broker's book lists as a LIMIT, so the breakeven scenario runs through `plan_price_result` with `book_overrides` listing the stop as SL; `plan_result`'s book lists every order as LIMIT.

## Rounding the breakeven price (2026-10-04)

An average over several fills, such as 1000.03, is rarely on the tick, and the broker refused the modify, so the stop stayed at its old price. `move_to_breakeven` rounds towards the passive side, which for a stop means away from the market, so the stop can only lock in a little profit, never a small loss. The tick comes from the parent's `tick_size`, which `PlanOrder._refuse_off_tick_prices` keeps for plans that read no prices.
