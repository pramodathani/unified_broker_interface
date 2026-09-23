# `liquidity_seeking.py`

## Why only the levels inside the limit are counted

A quote's depth often has a large quantity sitting a few ticks away from the touch, and counting it would make the threshold trivially easy to reach at a price the caller would never accept. The order would then fire, fill the small amount near the touch, and rest for the remainder — which is exactly the visible resting order the type exists to avoid.

So `reachable_quantity` walks the depth and adds only the levels at or inside `limit_price`. The scenario that pins this puts fifty units inside the limit and nine hundred just outside it, and the order stays hidden.

## Why what is displayed is not what is there

Two honest gaps, both stated in the class docstring rather than hidden.

Part of the book may itself be an iceberg showing a fraction of its size, so more can fill than was displayed. That is harmless — the order is capped at what is left to do.

Or the size may be gone by the time the order arrives, in which case less fills and the remainder rests at the limit. The next tick finds a leg already resting rather than starting again, because `placed_quantity` counts what was sent rather than what filled. That is deliberately conservative: it would rather leave an order resting than send a second one on top of the first.
