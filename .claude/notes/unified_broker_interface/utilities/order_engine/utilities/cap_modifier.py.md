# Notes on `unified_broker_interface/utilities/order_engine/utilities/cap_modifier.py`

## Why a cap is a modifier rather than part of each pricing

Today's peg, chaser and underlying peg each carry their own `cap_price`. In the design a cap is a modifier that sits beside any pricing setter, so a cap written once works on a peg, a chase or anything that comes later. `OrderPart` applies it after the setter has priced the body and to every new limit a moving order is sent, so the setter never has to know about it.

The design also lists a `price_limit` guard, which would refuse rather than hold a price past the limit. No type that exists today refuses in that way, so it is not built.
