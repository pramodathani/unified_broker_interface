# Notes on `unified_broker_interface/utilities/broker_orders/utilities/place_order_list.py`

## Why it copies `OrderChangeList` rather than sharing a base with it

The two lists read the same way from the outside: an `orders` array, `dry_run` beside it and nowhere else, a 400 per bad item and a 400 for the whole list only when the list itself is wrong. Their items are different things, though. A change names an existing order and is checked against the others for repeats; a placement is a new order, may carry any synthetic type, and loses any `broker` it names. Sharing a base would mean a base whose every method took a flag for which kind it was, so each list is its own small class, as the project's style asks.

## Why a list has a maximum and the change lists do not

A placed list can hold new orders at every broker at once, and each costs broker messages and engine work that a caller could not take back. `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACE_LIST_MAXIMUM`, 500 by default, bounds a mistake. Five hundred is fifty seconds of one broker's ten-a-second limit, or five across ten brokers.

## Why `dry_run` is written into every item's body

The engine runs each order from its own body, so a list's `dry_run` has to reach each body to take effect. Writing it there, rather than passing it beside the intent, means the engine needs no change to honour it and a dry-run list is answered exactly as the same orders sent one at a time with `dry_run` would be.
