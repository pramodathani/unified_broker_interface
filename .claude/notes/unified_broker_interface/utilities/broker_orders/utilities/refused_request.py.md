# Notes on `unified_broker_interface/utilities/broker_orders/utilities/refused_request.py`

## Why this left the blueprint

`RefusedRequestError` began in `unified_broker_interface/blueprints/orders.py`, where it was raised by every check that answers a request without calling a broker: a bad token, an unmapped instrument, an untrusted contract size, no broker able to take the order. It carries a body dictionary and an HTTP status and nothing else, so nothing about it was ever specific to Flask or to a blueprint. What kept it there was habit rather than design.

The order engine is why it had to move. When the engine refuses an order because no broker can take it, the API worker waiting on the reply has to answer the caller with exactly the body and the status that the direct path would have produced. Had the exception stayed in the blueprint, the engine would have needed its own parallel vocabulary of refusals and a table mapping one onto the other, and every refusal added later would have had to be added in two places. Sharing one exception means the refusal contract crosses a process boundary as data, with nothing in between to drift.

## Why `refusal` is a classmethod rather than a second free function

`OrdersBlueprint.refuse` built the body and returned the exception for its caller to raise. That body building is the only part worth sharing, so it moved onto the class as `refusal`. The blueprint's `refuse` still exists with the same name, signature and docstring and now delegates in one line, which is what keeps all 38 of its call sites untouched.

It returns the exception rather than raising it, which looks odd until you read a call site: `raise self.refuse(message, 400)`. Keeping the `raise` at the call site is what makes it obvious, when skimming a long method, which lines end the request.
