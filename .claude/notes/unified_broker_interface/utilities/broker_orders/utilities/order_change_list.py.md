# Notes on `unified_broker_interface/utilities/broker_orders/utilities/order_change_list.py`

## Why the list form is chosen by the `orders` key

`modify` and `cancel` keep their methods, `PUT` and `DELETE`, so the method cannot tell the two forms apart the way it does on the instrument routes. The presence of `orders` in the body does instead. The answer's shape therefore follows the form of the request and never the number of orders: a list of one still answers `{"results": [...]}`.

## Why the list takes no other key

Every key beside `orders` other than `dry_run` is refused, in the body and in the query string. The danger this closes is a caller writing `{"orders": [...], "price": 2501}` and expecting every order's price to change, or `broker` beside the list expecting it to apply to every order. Such a key would otherwise be silently ignored and the orders changed or cancelled without it. The message names the key and says to put it inside each order.

## Why `dry_run` is refused inside an order

`dry_run` is read once, beside the list or in the query string, and applies to every order. An item carrying its own `dry_run` is refused rather than honoured, so that a list can never be half shown and half sent because a caller marked some orders and missed others.

## Why repeated orders are refused

Two items that name the same order would send two changes to one order in one request, which is almost always a mistake and costs two messages from the broker's daily allowance. The second one is refused, naming the `request_index` of the first. Two items name the same order when their ids match and their brokers match or either gives none. The same id at two explicitly named brokers is two different orders, because brokers number orders independently, and both go ahead.

## No limit on the length

The user asked for no cap. A list's Redis cost does not grow in round trips, and its broker requests are paced by the four send threads.
