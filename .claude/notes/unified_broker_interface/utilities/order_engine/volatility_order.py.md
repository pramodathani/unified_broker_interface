# Notes on `unified_broker_interface/utilities/order_engine/volatility_order.py`

## Why it subclasses `UnderlyingPeg`

The plan said `Peg`. The volatility order follows another instrument exactly as the underlying peg does: it needs the same watched instrument, range, step, working leg and re-anchoring on a caller's change. Only the rule that turns the underlying's price into an order price differs, so subclassing `UnderlyingPeg` keeps that rule the only thing in this file. `UnderlyingPeg.bounded` was split out so both apply the range and rounding the same way.

## Why the order's own price is the worst it accepts

`PlaceOrderRequest` refuses a LIMIT without a price. Rather than accept a price and ignore it, the price is given a meaning a caller would want: a buy never pays more, a sell never takes less. It is read from the parent's body, so it stays what the order was placed with even after the caller moves the leg.

## The forward and the rate

Black-76 prices on a forward. A future of the option's expiry is that forward, so its price is used as it is. An index is a spot price, and is grown to expiry by `interest_rate`. The rate defaults to 0 rather than to a guess at the current rate, because a wrong default would be invisible in every price; a caller who watches the index and wants the carry should state it.

## Numbers from the offline suite

At 10:00 on 23 September 2026 a Nifty 25000 call expiring 29 September has 6.23 days to run. At 12.5% volatility with the index at 25000 and no rate, the model gives 162.85. The rule of thumb for an at-the-money option, 0.4 × forward × volatility × √time, gives 162.9. After a 100-point rise the premium is 218.00: about 50.3 from the delta of 0.503 and 4.9 from gamma.
