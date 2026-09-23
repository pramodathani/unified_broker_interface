# `post_only.py`

## Why refusing is the default

A post-only order exists to avoid taking liquidity. Quietly correcting a crossing price to the touch and sending it anyway would fill the caller's order at a price they did not ask for, which is a smaller version of exactly the thing they were trying to avoid.

So `refuse` is the default and answers 409 with the book that refused it, which is enough for the caller to decide what to do. `rest` is there because for a working algorithm that is genuinely what it wants — put it wherever it can rest — and having to make a second request for that would be silly.

## Why it does not watch the market

The first draft watched, and pulled the order back to the touch whenever the market came up to it. That is wrong, and wrong in an interesting way: an order the market has come up to is an order about to be traded against, which is the entire purpose of resting. Pulling it away means never filling.

A resting order that follows the touch is a peg, and `peg` is that type. The two are easy to confuse because both are about staying passive; the difference is that a peg is trying to stay near the price and this is trying to stay out of the way.

## Why the guarantee is honest about being approximate

On a crypto venue, post-only is enforced by the matching engine and cannot fail. Here the check happens before the order is sent, and the book can move in the tens of milliseconds the request takes, so an order that was passive when it left can cross when it lands.

That is stated in the class docstring rather than glossed, because the failure is silent: the order fills, the fill looks normal, and the only sign is the fee and the queue position the caller was trying to protect.
