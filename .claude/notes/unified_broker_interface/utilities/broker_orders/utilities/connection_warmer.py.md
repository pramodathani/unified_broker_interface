# Notes on `unified_broker_interface/utilities/broker_orders/utilities/connection_warmer.py`

## Why the warmer rotates rather than pinging one connection

Broker lanes send up to one order per worker at a time to one broker, so a pool has to have many warm connections, not one. With the pool handing out the connection that has waited longest, one warmer thread pinging one connection at a time reaches every connection in turn. It still holds only one connection at a time, so it takes at most one connection away from orders, which is what the extra place in the pool is for.

## Why the first round is sent back to back

A new pool holds only empty places. If the warmer waited its usual spacing from the start, orders in the first interval after a restart would open most of the connections themselves.

## Why the spacing counts from the start of a ping

Every ping holds its connection for `WARM_SETTLE_SECONDS`, one second for real brokers, before returning it. Spacing pings by `WARM_INTERVAL_SECONDS` divided by the pool size and then adding the settle time on top would make a round take the pool size times (spacing plus one second): about 47 seconds for Shoonya's pool of 31 at a 15-second interval, past its 45-second idle limit. Counting the spacing from the start of each ping makes a round take the interval or the pool size times the settle time, whichever is longer, which is about 31 seconds for a pool of 31. Every broker's idle limit, 45 seconds at the shortest, stays above that.

## Why a failed ping waits the whole interval

The first version of the rotating loop had no floor on the pause, and a broker that answers a ping with an immediate error, such as a refused connection, turned it into a tight loop: the offline suite's raising warmer made 462,978 pings in a few seconds. A failed ping now waits the whole `WARM_INTERVAL_SECONDS`, as the warmer did before rotation existed, and the first round stops at the first failure. That suite now makes 31 pings. A successful ping waits at least 50 milliseconds before the next, so a pool whose settle check is skipped cannot spin either.
