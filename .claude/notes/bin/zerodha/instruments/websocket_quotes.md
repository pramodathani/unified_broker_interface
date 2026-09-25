# bin/zerodha/instruments/websocket_quotes

## Why the feed subscribes to today's whole instrument master

Until 2026-09-16 the script read the Redis set `zerodha:quotes:subscriptions`, which held 15 hand-picked instruments, and carried them on a single websocket. The user asked for today's Zerodha instruments to be split into 24 equal parts with one websocket per part, and for the single socket that was already set up to be discarded, so that Zerodha runs exactly 24 quote sockets. The subscription set is therefore no longer read at all: the instrument source is `zerodha:instruments:master`, the hash `bin/zerodha/instruments/daily_feed` replaces every morning at 07:45 IST, which on 2026-09-16 held 112,657 instruments across NFO (35,636), NCO (25,129), MCX (16,656), BSE (12,849), NSE (10,236), CDS (7,548), BFO (4,590), GLOBAL (12) and NSEIX (1).

The set is left in Redis rather than deleted, because deleting it is a change to live data that was not asked for, and no code reads it any more.

## Why this exceeds Kite's documented limits, knowingly

Kite documents three websockets per api key and 3,000 instruments per websocket, and `bin/zerodha/orders/websocket_order_details` holds one of the three. The previous code enforced that with two constants: `MAX_INSTRUMENTS_PER_CONNECTION = 3000` rejected a larger `--per-socket`, and `CONNECTION_BUDGET = 2` refused to start when the instruments needed more connections than Kite would grant. Twenty-four sockets of about 4,700 instruments breaks both rules, so both constants were removed and the script now opens as many sockets as it is asked for.

The user was told the documented limits before asking for 24 sockets, so the limits are being tested deliberately rather than overlooked. What Kite actually does with the connections past its limit has not been observed: the expectation is that it refuses them at the handshake, in which case each refused socket reconnects with backoff on its own thread and the sockets Kite accepted keep streaming. Nothing in this change was run against the live feed.

## Why the split is by socket count rather than by batch size

Every other broker's feed takes `--per-socket`, a batch size, and opens however many connections the instrument count needs. That cannot express "24 equal parts", because 112,657 does not divide by any batch size into exactly 24 batches. `--sockets` says how many parts instead, and `split_into_parts` gives the first `count % sockets` parts one instrument more than the rest, which for today's master is one part of 4,695 and twenty-three of 4,694. A part that would be empty, when there are fewer instruments than sockets, is left out rather than opening a websocket that subscribes to nothing.

The tokens are sorted before they are split, so each socket carries a contiguous run of instrument tokens and a restart with the same master gives the same 24 parts. Kite's low token byte is the exchange segment, so sorting does not group instruments by exchange; no grouping was asked for and none is needed, since every socket writes into the same live hash and stream.

## Why names come from the master rather than from Kite's instrument file

The script used to download `https://api.kite.trade/instruments` at startup and keep the rows whose token was subscribed. With the master as the instrument source that download is redundant: the master holds the same file, cleaned, from 07:45 that morning, and reading 112,657 names out of it took 0.4 seconds against the live Redis on 2026-09-16, where a second download of the full file would cost far more. The column order comes from `zerodha:instruments:meta` rather than being assumed, because the master stores rows as bare JSON arrays. The download is kept as a fallback for `--tokens` when the master has not been filled.

## Why the subscribed-instruments hash is written in batches

`zerodha:quotes:instruments` used to be replaced with one `HSET` carrying every field. At 15 instruments that is nothing; at 112,657 it is a single Redis command of a few megabytes. `bin/zerodha/instruments/daily_feed` already writes the master 5,000 fields at a time for the same reason, so the same batch size is used here.

## What is expected to go wrong

Full-mode ticks for 112,657 instruments will outrun `bin/zerodha/instruments/store_quotes_to_db` during market hours, and anything Redis trims before the persister reaches it never gets to `zerodha.ticks`. The cap was 100,000 entries when the 24-socket change was made and the user raised it to 1,000,000 immediately afterwards, across all ten brokers, which buys ten times the catch-up room rather than removing the problem. Subscribing in a lighter mode than `full` would cut the volume at the source and has not been asked for.

Zerodha issues one token per session and every login invalidates the last, which is why `ZerodhaSession.log_in_again` (now in `stock_brokers/websockets/zerodha.py`) lets one socket at a time log in and skips the login when another socket has already replaced the token. That lock was written for two sockets. With 24 sockets reconnecting after a token dies, it is the same lock under twelve times the pressure, and it has not been exercised at that scale.
