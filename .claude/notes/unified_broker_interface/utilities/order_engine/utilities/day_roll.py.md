# `day_roll.py`

## The failure this prevents

`unified:orders:parents`, its open set and its child index all expire at the next 06:00 IST, which is right for almost everything: an order placed on Tuesday is finished on Tuesday, and a cache that cleans itself out is one nobody has to remember to clear.

For a parent that outlives a day it is a silent failure, and silent is the problem. The engine does not restart every morning. At six o'clock the keys expire underneath a running engine, `open_parent_ids` returns nothing, and the clock and price tickers find nothing to tick. The order is not lost — the event log still has it and the next restart rebuilds it — but it stops working, and nothing says so. A stop somebody armed on Monday for a position held until Friday simply is not there on Tuesday.

## Why it reuses the recovery path

`roll` calls the same `replay` and `rebuild` that startup calls. That is deliberate: the recovery path is exercised by every restart, so it is the one that can be trusted, and a second way of getting parents into Redis would be a second thing to keep correct.

Broker order ids are deliberately **not** reconciled here, unlike at startup. A rollover happens at six in the morning, hours before any exchange opens and hours after the last one closed, so nothing has changed at a broker since the state being rebuilt was written. Reading ten order books to learn nothing would be ten round trips on a schedule.

## Why a failed roll does not mark the day as done

`last_reset` is only advanced after a successful rebuild, so a failure is retried on the next pass through the loop. Marking it done and logging the failure would leave the caches empty until somebody noticed, which is exactly the silent not-working this class exists to prevent — with the added insult that the engine would believe it had handled it.
