# Notes on `unified_broker_interface/utilities/broker_orders/utilities/prepared_placement.py`

## What the class is for

`PreparedPlacement` is an order that has been given a broker and a built request but has not been sent. It is deliberately a holder with no behaviour: five attributes and a constructor, in the same shape as `broker_request.py` and `broker_answer.py` beside it.

## Why the seam exists at all

There was already one caller that needed to stop between choosing a broker and sending: a dry run answers with the request it would have sent. That alone would not have justified a class, because the dry run could read the local variables.

The order engine is the reason. Before an engine-placed order's request leaves, the engine writes a row saying what it is about to do, and commits it, so that a crash during the send leaves evidence that an order may exist at the broker. That is the whole basis of its recovery. It therefore needs a value it can hold, record and then send, rather than a single call that chooses and sends in one motion.

Splitting the seam while extracting the placement code, rather than later, was a deliberate choice. `test_runs/order_routes.py` compares the outgoing broker requests byte for byte against a recording, and that recording is the proof that extracting the placement logic changed nothing. Cutting the seam afterwards would have meant reopening a file the recording had already blessed, and doing it a second time under less scrutiny.
