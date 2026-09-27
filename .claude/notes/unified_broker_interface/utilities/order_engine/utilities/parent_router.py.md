# Notes on `unified_broker_interface/utilities/order_engine/utilities/parent_router.py`

## Why ownership is recorded before anything is sent

The worker placing an intent registers itself as the parent's owner as soon as the parent object exists, before `run` sends a leg. A fill can arrive while the first leg's request is still in flight; if the owner were recorded after `run`, the main thread would find no owner for that fill and give the parent a second one in another thread.

## Why unknown parents get an owner on first use

Parents recovered at start, and parents whose owner was forgotten at the day roll, have no owner in this process. They are given one the first time any work for them arrives, in the lane of the broker their legs went to, which `broker_of_document` reads from the stored record. A parent with no leg yet goes to the `unassigned` lane. Either way the first owner is kept for the rest of the day.

## Why owners are forgotten only at the day roll

Forgetting a parent's owner while work for it may still be queued would let the next piece of work go to a different worker, and two threads would then run for the same parent. The day roll waits until every worker is idle, which is the one moment forgetting is safe, and it keeps the owners dictionary from growing across days.

## Why the lane chosen at intake is a real broker choice

The main thread chooses an intent's broker with the configured selector and every skip check, exactly as a placement would, through `EnginePlacement.assign_broker`, and the worker's first legs then go to that broker. Without the binding, round robin would advance twice for every order, once at intake and once at the leg, and the lane would rarely match the broker the order went to. See the notes on `engine_placement.py`.
