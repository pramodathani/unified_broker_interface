# `price_trigger.py`

## Why there is a base class here at all

The standing preference in this project is a self-contained class per case rather than one parameterised mechanism, and five near-identical files would have been the safer reading of it. This is a base class because what the five share is genuinely one mechanism rather than a family resemblance: arm, watch, fire exactly once, record. Every line of that is identical, and the five differ only in which instrument they watch, which number out of its quote they compare, which way the comparison goes by default, and what they place.

The precedent is already in the package. `bracket.py` subclasses `oco.py` and `scale_out.py` subclasses `bracket.py`, for the same reason: the difference between them is what happens before the exits, not the exits.

## Why firing once needs writing down

The obvious implementation asks on every tick whether the price is past the level, and sends the child order when it is. That sends a child order on *every* tick from then on, because a price that fell through a level normally stays below it. Over an afternoon that is several thousand orders.

`triggered_at` goes into the parent's parameters and is saved before the child is placed, and a parent that has one is not asked again. It is written before rather than after for the same reason `leg_requested` is: if the engine dies between the write and the send, the honest state is "this may have fired", and a trigger that fires twice after a crash is far worse than one that does not fire at all and leaves a parent for somebody to look at.

## Why the default direction is the opposite of a stop's

Every type built on this fires when the price comes *to* the level: a buy waits for the price to fall to it, a sell waits for the price to rise to it. That is the buy-the-dip meaning, and it is precisely the direction a native stop cannot go, which is the whole reason these types have to run in the engine.

The hidden stop overrides the default, because it really is a stop and fires the other way. `trigger_direction` lets a caller say either explicitly, which is what turns a limit-if-touched order into a breakout entry.

## Why all legs go to one broker

`fire` passes `chosen_broker()` rather than letting the selector choose. A hidden stop places its backstop when it is armed and its exit perhaps an hour later, and by then the round robin has moved on several times.

A stop at one broker cannot protect a position at another. The two accounts know nothing about each other, so the exit would open a fresh short at the second broker while the original position sat unprotected at the first, and the account would end the day with two positions where it thought it had none. This was caught by an offline scenario whose exit went to Fyers while its backstop rested at Flattrade.

## Why `has_fired` looks at the legs as well as `triggered_at`

`triggered_at` is written into the parent's parameters and saved to Redis, but never to the event log. The log's `parent_received` row carries the parameters as the caller sent them, so a parent rebuilt by `EngineRecovery` after a restart has no `triggered_at`. Until 2026-09-24 that meant a trigger whose level was still crossed fired a second time on the first tick after a restart, sending a duplicate order; the offline scenario `a_fired_trigger_does_not_fire_again_after_a_restart` reproduced it as two `PlaceOrder` requests.

The legs are in the event log, so `has_fired` also treats any leg as proof of firing. The one exception is the `backstop` a hidden stop leaves resting when it is armed, which exists before the trigger fires. `GoodTillTriggered` asks the same question before expiring a parent, so a fired order that is still working is not marked cancelled after a restart.
