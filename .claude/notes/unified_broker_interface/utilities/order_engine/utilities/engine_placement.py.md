# Notes on `unified_broker_interface/utilities/order_engine/engine_placement.py`

## What is duplicated from the blueprint, and why that is the right amount

This class repeats the pipeline ordering `unified_broker_interface/blueprints/orders.py` uses, because the engine builds a broker request of its own and needs the same catalogue entry and the same credentials. About sixty-eight lines look very similar in the two files.

That duplication was measured before it was accepted. The original plan assumed forty-five lines; the real figure for copying everything was a hundred and four, and thirty-six of those were `find_instrument_id`, which is not I/O sequencing but a rule: no match is HTTP 404, more than one is HTTP 400 telling the caller to give an `instrument_id` instead. A rule living in two processes gets corrected in one of them.

So the route keeps the lookup and writes the resolved id into the intent, and what remains here is sequencing the two processes are entitled to differ on anyway. They already do: the engine checks no access token, because the route has, and it reads the warm identifier for a cache the route keeps per worker and the engine keeps for the whole day.

## Why the credentials are read per order

The first round trip re-reads every broker's login and settings for every order, which looks like an obvious thing to cache in a process that runs all day.

It is not cached because a broker's token can be replaced at any moment by any other process in the system — that is the whole point of `BrokerAPI._current_login` and of writing MongoDB first and Redis second. An engine holding a login it read an hour ago would send orders with a token that has since been invalidated, and at Zerodha every login invalidates the previous one, so this is not hypothetical. The direct path re-reads them per request for the same reason.

## Why the instrument cache is worth more here

`InstrumentCache` exists so a gunicorn worker does not re-read the same catalogue entry for every order. In a worker its value is modest, because there are two workers and each starts cold.

In the engine there is one process for the whole day, so after the first order on an instrument the entry is held for as long as the warm lasts. Most orders therefore skip the three catalogue reads entirely. They still cost a round trip when the configured selector queues a command of its own, which `round_robin` does and `fixed_priority` does not.
