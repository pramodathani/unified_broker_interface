# Notes on `unified_broker_interface/utilities/broker_orders/utilities/connection_pool.py`

## Why a warmed broker's pool hands out the oldest connection

urllib3 keeps a pool's idle connections in a last-in, first-out queue: the connection returned most recently is handed out first. A warmer that pings one connection at a time therefore reuses the same connection on every ping, and the others sit idle until the idle limit closes them, at which point an order opens a new one and pays for a TLS handshake. Checked with a local server on 2026-09-27, eight single pings on a pool of four used `D, D, D, D, D, D, D, D` in the default order and `A, B, C, D, A, B, C, D` with a first-in, first-out queue.

Setting `QueueCls` to `queue.Queue` is urllib3's own class attribute for choosing the queue, so this is not a reach into private code. It is set on the instance before the parent constructor runs, which is the only moment the parent reads it.

## Why it is only for warmed brokers

A first-in, first-out pool spreads requests over every connection it has. With a warmer that is exactly right, because the warmer keeps every one of them fresh. Without a warmer it is worse than urllib3's default: each connection sits idle for longer between requests, so more of them pass the idle limit and are reopened, where the default keeps one busy connection hot.

## Why the empty places are left as urllib3 makes them

urllib3 fills a new pool with one empty place, `None`, per connection it may hold, and opens a connection when it takes one. In a first-in, first-out pool the empty places are reached before any connection returned later, so the warmer's first round of back-to-back pings opens every connection, and a place emptied by a failed request is filled again within one round. A queue that preferred open connections over empty places was tried and dropped: the warmer's first round then reused one connection over and over and never filled the pool.
