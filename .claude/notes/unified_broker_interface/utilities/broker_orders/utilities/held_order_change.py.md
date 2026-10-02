# Notes on `unified_broker_interface/utilities/broker_orders/utilities/held_order_change.py`

## Why a held order is named by parent_id

A held order has no broker order id until it fires, so the ordinary modify request, which finds an order in the brokers' books, cannot find it. `parent_id` is what the place route answered with. Only `price` and `quantity` are accepted, because they are the terms a virtual limit is held by; any other field, including `order_id` or `broker` beside `parent_id`, is refused so a caller never believes a change was made that was not.

## Plan parts (added 2026-10-02)

`part` names a plan part that has not been sent, and only with it may `trigger_price` be given; without it the body is a held order as before, and a `trigger_price` there gets a message pointing at `part`. `command_arguments` adds `part` and `trigger_price` only for a part, so the arguments of a held order are unchanged and the existing recordings did not move.
