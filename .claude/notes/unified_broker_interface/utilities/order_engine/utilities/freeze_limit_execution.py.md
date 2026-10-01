# Notes on `unified_broker_interface/utilities/order_engine/utilities/freeze_limit_execution.py`

## Choosing the broker before splitting

Each broker publishes its freeze quantity in its own units, so the split needs the broker first, as today's freeze slicer has it. `due_pieces` calls `placement.prepare`, which runs the selector, keeps the broker in the execution's memory, and `OrderPart.send_due` passes that broker to every slice's placement. The offline scenarios `a_plan_*freeze*` send the same requests as today's.

## Not innermost

The design had the freeze limit applied innermost to every piece of any execution. A plan's order takes one execution, so this is an execution of its own; an order that is both above the freeze quantity and sliced over time is not built.
