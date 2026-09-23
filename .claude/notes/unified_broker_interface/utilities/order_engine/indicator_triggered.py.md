# `indicator_triggered.py`

## Why this is not an indicator library

The name invites a relative strength index, a Supertrend, a moving-average cross and an open-interest change, and none of them is here. They need a history of bars the engine does not keep and a recalculation schedule it does not run, and adding those would be building a second system — a bar builder, a warm-up period, a backfill on restart — inside an order engine.

What is here is the part that genuinely belongs in an order: one value out of the live quote, a level, and a direction. Anything computed belongs in whatever decides to place the order, which then sends a plain limit or a limit-if-touched with the number it worked out. That division keeps the engine's job "place what you were told, when you were told" rather than "have opinions".

`average_price` is the field that makes this type worth having on its own. It is the day's volume weighted average price, and "buy when the price comes back below the day's average" is a complete idea expressed in one order that cannot be written as a native stop, because the level moves.

`previous_close` is there because "trigger if it goes green for the day" is a real thing people want and is genuinely a property of the quote rather than of a strategy.
