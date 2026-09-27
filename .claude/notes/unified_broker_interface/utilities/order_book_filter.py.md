# Notes on `unified_broker_interface/utilities/order_book_filter.py`

## Why filtering happens in the route, over the whole document

The order and trade books are one document each, rebuilt every half second by the combiners. The plan for broker lanes proposed a per-order hash and a time index beside the document, so a filtered read would touch only the orders asked for, and a combiner that rebuilt only the brokers whose books changed. Neither was built. Knowing which books changed needs every poller and every order websocket script to publish a marker when it writes, which means editing twenty scripts that run against live accounts, for a gain that matters only well above today's few thousand orders a day. Filtering the served document in the route gives callers the small answers the plan was after, at the cost of the route reading the whole document; that cost is worth measuring before the larger change is made.

## Why there is no `since` filter

Each broker writes its order and trade timestamps in its own format, with or without a date, an offset or fractions, which is why the combiners sort only within a broker. Comparing them across brokers to answer "since" would give wrong answers quietly. `order_id`, `parent_id` and `intent_id` already let a caller who placed orders find them, and `cursor` pages through a long list.

## Why `status=open` means "not finished"

The shared vocabulary's finished statuses are `COMPLETE`, `CANCELLED`, `REJECTED` and `EXPIRED`. Anything else, including a status nobody has mapped, is treated as open, for the same reason flatten cancels an unmapped status: an unknown status is far more likely to be a live order with a new spelling than a finished one.
