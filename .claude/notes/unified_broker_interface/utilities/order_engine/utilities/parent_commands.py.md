# Notes on `unified_broker_interface/utilities/order_engine/utilities/parent_commands.py`

## Why changes to engine orders go through the engine

Before broker lanes, `PUT /api/orders/modify` and `DELETE /api/orders/cancel` sent every change straight from an API worker, including changes to the engine's own legs. The engine learned of a cancel only when the broker's update arrived, and never learned of a changed price or quantity at all, because the order-update follower records only status, fills and the exchange id. A trailing stop would move a trigger the caller had just set back to where it thought it should be, and an OCO pair would reduce its sibling from a quantity that was no longer true.

With lanes, only the worker that owns a parent may touch it. So a change to an engine order is handed to that worker as a command intent, and the parent's own order type makes it. The user chose, on 2026-09-27, that a modify should be carried out and the type should carry on from the new values, rather than refused; `on_leg_modified` is the hook each type uses to do that.

## Why the route still checks the change

The modify route already checks a change against the stored order, the lot size and the tick size, and converts the quantity into the broker's own terms. Those checks stay in the route, which then hands the engine plain numbers: a quantity in the broker's terms and the prices. The engine therefore repeats none of the route's rules, and a dry run is answered by the route without involving the engine at all.

## Why only price, trigger price and quantity

An order type works from its leg's price, trigger price and quantity, and `EnginePlacement.modify_leg` changes exactly those. Changing the order type, the validity or the disclosed quantity underneath a type would leave it managing an order that is not the one it placed, so the route refuses those with 409 for an engine order.

## Why a cancelled leg stays acknowledged

After an accepted cancel, the leg is still recorded as it was until the broker's own update says it is cancelled, as with every cancel the engine sends. An accepted cancel is a promise, not a fact: an order can fill in the moment before the exchange acts on it, and treating the promise as the fact is how a filled order gets forgotten.

## Why a halt answers before it has run

Flatten must not wait for every worker to reach its halt, because a worker may be in the middle of a slow broker call. The main thread hands each open parent's owner a halt and answers at once. Each worker runs work in arrival order, so a fill or a tick that reaches it after the halt finds the parent already cancelled, which is the guarantee flatten needs.

## `part` and `dry_run` on `cancel_parent` (added 2026-10-02)

`cancel_parent` with `part` hands the cancel to `runner.cancel_part`, which only a plan implements; every other type refuses with 409, as `modify_part` does. A whole-parent dry run is answered by `cancel_parent_dry_run`, which lists the legs a cancel would be sent for under `resting_legs` and changes nothing. The reason recorded for a whole-parent cancel became `cancelled by the caller`, because the command is now sent by two routes and the old text named only `DELETE /api/orders/parents`.

## Caller cancels reach the order type (2026-10-05)

`cancel_leg` hands an accepted cancel to `runner.take_caller_cancel`, so a plan does not send again an order the caller cancelled by `order_id`.
