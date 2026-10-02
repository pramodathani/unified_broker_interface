# Notes on `unified_broker_interface/utilities/broker_orders/utilities/parent_cancel.py`

## Why it mirrors `HeldOrderChange`

`DELETE /api/orders/cancel` was made consistent with `PUT /api/orders/modify` on 2026-10-02, so a cancel named by `parent_id` is validated by a class of its own, as a held change is, rather than by widening `CancelOrderRequest`, whose every field is about a broker order. `parent_id` and `part` are read from the body only, as modify reads them; `dry_run` is read from the body first and the query string second, as the rest of the route reads it.

## Why `order_id` or `broker` beside `parent_id` is refused

A body naming both would leave it unclear which order the caller meant, and cancelling the wrong one cannot be taken back. Modify refuses the same fields beside `parent_id`.

## Why `command_arguments` adds `part` and `dry_run` only when given

The `cancel_parent` command's arguments were `{"parent_id": ...}` for the parents route. Adding the new keys only when they carry something keeps the arguments of a plain cancel unchanged, so the recorded intents did not move.
