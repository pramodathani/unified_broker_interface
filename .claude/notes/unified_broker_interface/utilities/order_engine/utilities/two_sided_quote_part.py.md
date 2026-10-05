# two_sided_quote_part.py

## When it is done (2026-10-02)

`OrderPart`'s done rule ends a part once every broker order has finished. A quote whose bid and ask both fill between two ticks would then end, though today's type quotes both sides again on the next tick and only ever ends when cancelled or at the day's end. So the part is done only once it has been stopped, through `cancel_rest`, by its join or the caller, and its orders have finished after that. `stopped` is recorded with a message so a restart keeps it.

## Sides without memory

Today's type gives its legs the roles `bid` and `ask`. Every leg of a part has the part's path as its role, so the bid is the part's resting buy and the ask its resting sell; at most one of each rests at a time, so no memory is needed.

## The size of each quote

The size is the body's quantity as the order's own context sees it, with the order's own `quantity` written over the body's, read through `read_order` on every tick as today's type reads the body.

## Repeated cancels under an Either join

In the scenario where an Either join cancels the quote, the quote's second order is asked to cancel twice: the first cancel's confirmation settles the plan again, and the join asks every unfinished sibling to cancel again. This was how every plan part under a cancelling Either join behaved. On 2026-10-02 `OrderPart.cancel_once` fixed it for every part, and the scenario now sends two cancels.

## Refused re-quotes, a missing quantity, and a spread past zero (2026-10-05)

`move` does not quote a side again when its last order was rejected; a margin refusal was sent again every second. `prepared_own_memory` refuses a body without a quantity (a `quantity_reference` alone divided by None in `wanted_prices` and answered 503 InvalidOperation), and tells a half spread that puts the bid at or below zero apart from a quote that carries no fair price.
