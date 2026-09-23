# `repricing_throttle.py`

## Why this is separate from the rate budget

They answer different questions and either can be satisfied while the other is not. The rate budget asks whether the system as a whole may send another request in this second. The throttle asks whether this particular order has been left alone long enough that moving it again is worth a request.

An account well inside a budget of eight requests a second can still be moving one order eight times a second, all day, on one instrument. The budget sees nothing wrong, because nothing is wrong by its measure. The order-to-trade ratio notices eventually, but only after the damage, and only as a number nobody is watching in the moment.

## Why it refuses rather than waits

The rate budget waits for a token, because an order held back for a few hundred milliseconds is the same order and still wants to be sent. A move is not like that. A limit price worked out from the quote a second ago is the wrong price by the time a token arrives, and sending it puts the order somewhere the market has already left. So a move that is too soon is dropped, and the next tick works out a fresh price from a fresh quote.

## Why it is held in memory and not written down

Exactly one engine runs, guaranteed by `unified:orders:engine:lock`, so there is no second process the memory would have to be shared with. Writing it down would mean a Redis round trip on every move, to protect a fact that stops being interesting a second after it is written.

After a restart the map is empty and every leg's first move is allowed at once. That is the right answer rather than a tolerable one: a leg nobody has touched since the engine came back should be brought to where it belongs immediately, not made to wait out a gap measured from a move that happened before the crash.

## Why `record` is called after the broker accepts

A move the broker refused did not move anything. Starting the gap from the attempt would leave the order sitting at a price the market has left, waiting out a throttle for a change that never happened.
