# `hidden_stop.py`

## Why it watches the opposite touch

A long is protected by a sell. A sell *rests* on the offer and *fills* against the bid, and it is the fill that decides whether the position can actually be got out of, so the bid is the number to compare against the level. In the code that is `opposite_touch` of the exit side, not `own_touch`.

The first draft had `own_touch` and was wrong by exactly one spread, which on a liquid instrument is five paise and on an illiquid option is several rupees. The offline scenario that catches it puts the bid at 994.90 and the offer at 995.20 around a level of 995: the correct reading fires, the wrong one does not.

Watching the book at all, rather than the last traded price, is the main thing this type buys over a native stop. A native stop watches the last trade, and a single print at a price nobody was standing behind — the freak trades that got stop-loss-market withdrawn from NSE options in 2021 and from BSE entirely in 2023 — closes a position the market never really left. A bid is a price somebody is committed to.

The last traded price is still the fallback when the book has no bid at all, because a stop that cannot read the book is better off using a worse number than not firing.

## Why the backstop exists and why it is placed first

The Atlas is blunt that the one thing a native stop has which no amount of code replaces is that it is not in your code. It sits in the exchange's stop book and fires at exchange speed whether or not the engine, the machine, the network or the quote feed is working.

So `backstop_price` places a real stop-loss limit, deliberately further away than the hidden one. In normal running the hidden stop fires first, on a better trigger and at a better price, and cancels the backstop. When the engine is not there, the backstop is: further away, worse, and real.

Both of its prices are required together, for the same reason `ExitLegs` requires both: a stop-limit whose limit sits at its trigger will not fill when the price runs through it, which is the one condition it exists for.

## Why the cancel comes before the exit

The same rule the kill switch follows. A resting stop left alone while the exit fills can trigger afterwards, and then it is not closing a position any more — it is opening a brand new one in the opposite direction, unattended, with nothing left watching it.
