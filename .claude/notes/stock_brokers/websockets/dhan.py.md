# Notes on `stock_brokers/websockets/dhan.py`

## Where this came from

The classes were moved on 2026-09-25 out of `bin/dhan/instruments/websocket_quotes` (`DhanSession`, `QuotesSocket` and the helpers `unpack`, `split_packets`, `true_epoch` and `apply_previous_close`) and `bin/dhan/orders/websocket_order_details` (`OrderUpdatesSocket`). The decoding is the same arithmetic as before, including the key order of the tick and of `ohlc`, which for Dhan is open, close, high, low in the quote and full branches because that is the order the old code inserted them in. The offline recording in `test_runs/websocket_feeds/` was taken against the old scripts and reproduces every tick.

## Why the quote socket gives up later than the base class

`DhanQuotesSocket` overrides `_gives_up_after_logging_in_again` to give up only once six connects in a row have failed. That is what the old quote loop did: its give-up test was `logged_in_again and failed_connects >= MAX_FAILED_CONNECTS`, without the "refused again" half the other loops had. The effect, pinned by the scenario `dhan.quotes.refused_again_logs_in_again`, is that a quote socket refused with a disconnect code straight after logging in again logs in again rather than giving up. The old code gave no reason. A plausible one is that Dhan's disconnect packets are also sent for reasons that are not about the token, but that has not been confirmed against the live feed.

## Why the order socket logs in again without checking the token

The old order socket logged in again whenever it was refused: it logged "Logging in to Dhan again." and constructed `DhanAPI`, without first checking whether another process had already replaced the token, which is what the quote sockets' `DhanSession.log_in_again` does. To keep that behaviour exactly, `DhanSession` has a second method, `log_in_again_without_checking`, and the order socket uses it. The scenario `dhan.orders.token_replaced_elsewhere` pins it: the order socket logs in even though another process already has.

Whether the check was left out on purpose is not recorded anywhere. Adding it would stop a needless second login when the quote feed or a poller has just logged in, but it is a change of behaviour and was not made as part of the move.

## Why the order socket shares the session

Sharing `DhanSession` with the quote sockets, rather than keeping a `DhanAPI` of its own, lets the script log in before it registers the merge script, which is the order the old socket did them in, and gives the order socket the same `credentials()` the quote sockets use. The client id and token it sends in its login message are read the same way as before, from the API object's settings and its current login.

## The order alert without an order number

As with Zerodha, the socket hands over every `order_alert` message's `Data` and the script normalizes it. An alert without an order number used to be logged by the socket as "Ignoring a message of type 'order_alert'" among the message's other lines; the script now logs it as "Ignoring an order update without an order number", after them. Nothing written to Redis changed.
