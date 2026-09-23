# `limit_if_touched.py`

## Why `limit_price` is required rather than defaulting to the trigger

Defaulting it would make the type easier to ask for and would produce, silently, a completely different order from the one most callers mean. A limit resting at exactly the level that just fired it is an order asking to trade at a price the market has by definition already reached and is moving away from, and it usually sits unfilled.

The two prices differing is the entire point of the type. If they were the same, a resting limit order would have done the job without any engine at all.

## Why this is the shape almost every conditional order really has

An alert that places an order, a broker's trigger sheet, a "buy when it breaks out" button in an app: all of them watch one number and send a limit at another. `cross_instrument` is this class with a different instrument being watched, and `indicator_triggered` is this class with a different field of the quote being watched. Recognising that early is what kept those two to a few dozen lines each.
