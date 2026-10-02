# from_fill_pricing.py

Added on 2026-10-02 to fix the two-sided breakout's exits, which were absolute prices that could not suit a break either way: after a downward break the target was a marketable buy above the range and the stop's limit sat on the wrong side of its trigger. The user chose distances from the fill over six per-side absolute prices.

The pricing averages the fills of every leg whose role is in `opened_by`, which the plan reader copies from the Then join (the same list `OrderPart.opened_by` gets). Under the breakout's Either-of-two-sides first plan only the side that broke has filled, so no side has to be chosen explicitly. It falls back to a leg's `price` when the broker has not given an average price, as `FromParentFillPricing` does.

Prices are rounded half up to the nearest tick and quantized to it, so they print like every other price ("1015.00" rather than "1015.0"). A plan holding a `from_fill` part stores its tick size at placement even though the pricing reads no quotes (`PlanOrder.run`), because otherwise nothing would be rounded.

The stop variant counts as a resting stop for `stop_not_sliced`; the target variant does not.
