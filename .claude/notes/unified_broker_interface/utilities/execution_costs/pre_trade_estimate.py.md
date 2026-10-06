# Notes on `pre_trade_estimate.py`

## Why the model is joined to the book walk this way

The square-root law is usually stated for a whole order: Δ ≈ Y σ √(Q ÷ V), measured from the mid-price. Applying it to the whole order would throw away the visible book, which for every order measured up to 2026-10-06 is the exact answer. So the estimate uses the book for what the book shows, counts any left-over quantity at the last visible level's price, and adds the square-root move only for the left-over quantity. It is an approximation at the join, chosen because it reduces to the exact answer whenever the book covers the order, which is the common case.

`beyond_book` spreads the left-over quantity's impact over the whole order, so all three parts are per unit of the whole order and add up to the total.

## Rounding

Each part is rounded to four places and the total is the sum of the rounded parts, so the parts always add up exactly in a printout. The total can therefore differ from an unrounded calculation by up to 0.00015 a unit: the 1,200-unit example's exact total is 0.38125, shown as 0.3812, and its rupee figure 457.44 rather than 457.50. That was judged better than parts that visibly do not add up.

`rounded` also removes the sign from a zero, which a sell's unchanged price otherwise carries as `-0.0000`, the same fix as in `ExecutionCost`. The small helper is repeated rather than shared, in line with preferring self-contained classes.

## Units and rupees

The quantity is in units, as the order engine's requests are, and the book's quantities are in units, as the unified quote feed and `unified.ticks` hold them. So `rupees` is right in every market, unlike `ExecutionCost.total_rupees`, which has to work from the fill quantity a broker reported.
