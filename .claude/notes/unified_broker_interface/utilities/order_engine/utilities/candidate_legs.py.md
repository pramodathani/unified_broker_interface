# `candidate_legs.py`

## Why a candidate names an instrument id rather than a symbol

Every type before these traded one instrument, because the REST route resolves the instrument before the engine sees the intent and writes one id into the parent. A basket, a one-cancels-all group and a legged spread need several, and there is nowhere in that route for a second one to come from.

Resolving an identity is not a lookup. It is a set of rules about ambiguity, near matches, expiry conventions and which exchange a symbol belongs to, and it lives in one place in the REST layer for exactly that reason. Putting a second copy inside the engine so that a basket could say "RELIANCE" would mean two answers to the same question, which will eventually disagree, and the disagreement would show up as an order on the wrong contract.

So a candidate names `instrument_id`. It is a real cost to the caller and a small one in practice: the unified catalogue is keyed by it, every order answer carries it back, and anything assembling a basket of five instruments has already looked all five up to decide it wanted them.

## Why repeating an instrument is refused

Two legs on one instrument in one group cannot be told apart afterwards. The order update stream keys on the broker's order id, which works, but every human-facing view — the answer's leg list, the event log, a question like "what did the basket do on RELIANCE" — collapses them.

There is no case where two legs on one instrument in one basket is clearer than two baskets, or than one leg of the combined size, so it is refused rather than supported.

## Why a candidate carries only what differs

A basket of five stocks bought the same way should be five instrument ids and five quantities, not five copies of the product, validity, order type and side. So a candidate starts from the parent's own body and overrides only the fields it names.

The `synthetic` block and the price and quantity references are dropped rather than inherited. A reference resolves against one instrument's quote or one position, and inheriting it would silently resolve it against the wrong one.
