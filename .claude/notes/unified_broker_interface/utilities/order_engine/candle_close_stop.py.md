# `candle_close_stop.py`

## Why it subclasses the hidden stop

Everything about firing is identical: the same marketable exit, the same cancel-the-backstop-before-exiting ordering, the same handling of a position it does not own. The only difference is what the level is compared against.

So `watched_price` is overridden to return the close of the bar that just ended, and `None` on every other tick. The price trigger already treats a missing price as "nothing to decide yet", which turns out to be exactly the semantics needed: the stop asks its question once per bar and does nothing at all in between.

That is the whole type in one override, and it also means the backstop comes free — which matters more here than anywhere else.

## Why the backstop matters more here

Between the level being crossed and the bar closing, **nothing is protecting the position**. That is not a side effect, it is the deliberate behaviour: sitting through the wick is the point. But it means a genuine breakdown at the start of a fifteen-minute bar is unprotected for fifteen minutes, and the exit when it comes is at the close rather than at the level.

An order placed mid-bar is also unprotected until the first bar ends, because there is no history to judge on.

Both are arguments for setting `backstop_price`, and the class docstring makes them rather than leaving the trade-off implied.

## Why `tick_moment` is an attribute

`watched_price` needs the tick's moment to know which bar the price belongs in, and the method it overrides takes only a view. Passing the moment through would mean changing the signature of `watched_price` for every trigger type so that one of them can use it.

An attribute set at the top of `on_price_tick` and read a moment later, in a call chain that is direct and single-threaded, is the smaller cost. It is declared on the class with a default so it can never raise an `AttributeError`.
