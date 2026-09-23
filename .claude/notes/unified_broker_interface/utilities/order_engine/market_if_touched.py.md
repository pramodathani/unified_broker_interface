# `market_if_touched.py`

## Why this cannot be a resting limit order

The obvious objection is that "buy when the price falls to 990" is just a limit order at 990, and the difference is worth stating because it decides which one a caller should ask for.

A resting limit at 990 is visible in the book. It fills at 990 or better and never worse, and it may sit through the level being touched without filling at all, because everybody ahead of it in the queue gets served first and the sellers may run out. A market-if-touched order is invisible until it fires, and then it accepts what the market is offering, which may be worse than 990. One is certain of the price, the other is certain of the trade.

There is a second difference that matters more in practice: a resting limit shows your hand. In a thin option book a large bid sitting at a round number is information other people trade against.

## Why the buffer is in ticks rather than a percentage

The order this fires is the Atlas's marketable limit, priced past the opposite touch so that it clears the level that is there. How far past is a question about the book's granularity, not about the price level: two ticks is two ticks whether the instrument trades at ₹50 or ₹50,000, and it is the number of price levels the order will sweep.

A percentage would be a different and worse question. Half a per cent of ₹50,000 is 250 rupees, which on a five-paise tick is five thousand levels, and the exchange's price bands would reject the order long before it got there.
