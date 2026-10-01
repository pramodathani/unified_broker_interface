# Notes on `unified_broker_interface/utilities/order_engine/utilities/all_at_once_execution.py`

## Why "sent" is read from the broker orders, not from memory

The first version kept `sent: True` in the part's execution memory, written without a recorded event. The offline scenario `a_plan_bracket_behaves_the_same_with_a_restart_between_fills` rebuilt the parent from its events, lost the flag, and the target exit was sent a second time. Reading "has this order gone" from the part's own legs, which recovery always rebuilds, makes a duplicate impossible. The same rule now holds for every execution: memory keeps only what cannot be read from the legs.

## Why it grows by changing its order

A bracket's exits grow with the entry's fills. With one resting order per exit, changing its quantity is one request and keeps its place in the queue, which is what today's bracket does, so `changes_its_order_to_grow` is true here and false for every execution that sends several pieces.
