# `trailing_stop.py`

## Why the ratchet is the whole type

A stop that followed the price in both directions would be moved down on every pullback and would never fire. It would pass every casual reading of the code, produce sensible-looking modify traffic all day, and be discovered only on the day the market kept going down.

So `improves_watermark` is the one method in `TrailingOrder` worth reading twice, and the offline scenario that matters most is the one where the market runs to 1040 and then falls back to 1015: the stop has to still be at 1030.

## Why `transaction_type` is the side that opened the position

It is the convention every type that protects a position follows here — `oco`, `bracket`, `scale_out` and `hidden_stop` all read it the same way — so a long is protected by asking for a BUY and the engine works out that the stop is a sell.

The alternative, asking the caller for the exit side, reads more directly for one order and reads wrongly across a set of them: somebody protecting a long position would have to remember to say SELL here and BUY in the bracket that opened it.
