# Notes on `bin/stoxkart/order_updates`

## How the socket was found

Stoxkart's developer documentation offers only a postback URL for order status, which needs a public web server. While watching Stoxkart's trading website in a separate Chrome profile on 2026-09-15, the page opened `wss://openapi-v2.stoxkart.com/websocket/v2/connect?x-client-id=<client>&x-platform=web&RequestId=<id>` on port 443, and its code showed the sequence: `POST /websocket/authenticate` with a session token and `x-platform: web`, read `data.RequestId`, connect, send `{"type":"heartbeat"}` every 30 seconds, and parse each text frame as JSON.

## Why this is the API's access and not the website's

The same authentication call was made with the API app's own access token. With `x-platform: api` Stoxkart answered HTTP 200, `"Authentication successful, server ready to accept WS"`, on both `openapi-v2.stoxkart.com` and the documented `openapi.stoxkart.com`. With `x-platform: web` it refused the same token with `AuthorizationError`. The script only ever sends `x-platform: api`, so it uses the access Stoxkart grants the API app. A connection with the `RequestId` from the API authentication stayed open for 25 seconds without error.

## Why the script waits five minutes after being evicted

The website's socket code closes itself when the close reason contains `new incoming connection`, and treats that as "evicted by another app for this client". Stoxkart therefore allows one order socket per client, and the newest connection wins. Reconnecting at once would take the socket back from a person using the website, who would take it back on their next focus, and the two would evict each other every few seconds. Waiting five minutes bounds how often that happens. An order change made while this script is evicted still reaches `stoxkart:orders:orders` through `bin/stoxkart/orders`, which polls the order book every second.

## What the first updates showed

The first updates arrived on 2026-09-15. Three NSE orders sent after the close each produced an update within a second, with `order_status` `REJECTED`, a blank `order_timestamp` and blank `exch_order_id`. Two after-market orders produced no update when they were placed, and one each when they were cancelled, with `order_status` `AMO CANCELLED`. The update's names matched the normalizer's second choices - `order_status`, `trading_symbol`, `transaction_type`, `product` - so every field was read correctly without a change.

## Why the entry carries its own `variety`

The cancellation updates for the two after-market orders said `variety` `NORMAL`, while the order book said `AMO`. The REST API's cancel endpoint builds Stoxkart's cancel path from the variety, so a socket update written last would have sent a cancel to `/orders/normal/`. The script therefore stores a top-level `variety` beside the raw update: an `AMO` or `BO` variety already stored for the order is kept, a status beginning with `AMO` means `AMO`, and only otherwise is the update's own `variety` used.

## Why the normalizer reads several names for most fields

No order update had been received when the script was written, because Stoxkart refused API orders with `invalid algo_id` and the user's live test orders were never placed. The website's update handler reads `order_status` and `variety` from an update, which suggests an order object with names close to the order book's but not identical to them, since the order book uses `status`. The normalizer therefore takes each field from the order book's name first and from the likeliest alternative second, and every message is logged at INFO with its first 300 characters. The first real update should be compared with the stored `data` and the table in the docstring corrected.

## Why the stream entry carries the normalized order

Other brokers' stream entries are `{"timestamp", "data"}`, and `bin/<broker>/persist_orders` and `bin/unified/order_updates` each carry a copy of that broker's normalizer to rebuild the order. Because Stoxkart's normalizer is provisional, three copies would have to be corrected together when the real format is seen. The entry therefore also carries `order`, which `bin/stoxkart/persist_orders` stores and `bin/unified/order_updates` uses directly, so the one normalizer in this script is the only one to correct.
