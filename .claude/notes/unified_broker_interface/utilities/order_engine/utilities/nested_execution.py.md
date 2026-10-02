# nested_execution.py

## Neither execution changes (2026-10-02)

Executions work out what they have sent from the pieces they are shown, reading only each piece's quantity, filled quantity, whether it has finished, and its state. A nested execution therefore shows the outer execution its released slices as `SlicePiece`s with those four, and each slice's inner execution that slice's real broker orders. No execution needed to learn about nesting.

## Which broker order belongs to which slice

Executions return quantities, not broker orders, so the leg ids are unknown when a piece falls due. `OrderPart.send_due` prices every due piece before sending any and places them in order, so the n-th broker order of the part is the n-th quantity ever returned; `leg_slices` records the slice number of each in that order. A placement the broker rejects still creates a leg, so the count stays aligned.

## Which pairs

The outer execution must release slices of a size it decides: twap, vwap, front_loaded, participation and iceberg do. Ladder sets each piece's price, which `send_due` applies only to a plain ladder; freeze_limit sends to one broker it chooses; top_up and daily answer fills and days, so none of them nests. The inner execution must work a fixed quantity: iceberg and the three timed executions. Two levels are enough for every combination the design names, so three are refused.

## State of a slice

Participation, book depth and top-up stop on a rejected last piece, and the iceberg asks whether its last piece filled, so a slice carries a state: `filled`, `rejected` when every broker order was refused, `cancelled` when it finished otherwise, and `working`. The first draft left it out and an outer iceberg would have failed; the iceberg-outside scenario keeps that tested.

## Restarts

The slices and each slice's inner memory are recorded with the order whenever a piece is sent. A new slice whose inner execution sends nothing at once is kept without an event, so a restart in that moment would release it again; every inner execution allowed sends its first piece at once, so this does not arise.
