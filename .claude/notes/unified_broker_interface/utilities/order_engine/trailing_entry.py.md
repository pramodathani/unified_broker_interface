# `trailing_entry.py`

## Why this is worth having as its own name

Mechanically it is `trailing_stop` with the stop on the other side, and the registry could have carried one type with a flag. It has its own name because what it is *for* is completely different, and a name is how somebody finds a type they have not met.

A trailing stop is risk management on a position you hold. A trailing entry is a way of buying a falling market without guessing where the bottom is: the trigger follows the low down, and the first bounce of the stated size takes the trade. Nobody looking for the second would find it filed under the first.

## Why it rests at the exchange without any special pleading

A buy stop's trigger sits above the last traded price, which is the direction Indian brokers allow a native stop to be placed in. So unlike the market-if-touched family, this one needs no engine-side trigger at all: the exchange holds it and fires it, and the engine's only job is to keep lowering it.

That makes it the cheapest of the watching types to run and the only one that still works, at its last trigger, if the engine stops.
