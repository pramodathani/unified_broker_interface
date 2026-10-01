# Notes on `unified_broker_interface/utilities/order_engine/utilities/ladder_execution.py`

## Why the rungs set their own prices

Every other execution's pieces are priced by the order's pricing. A ladder's rungs differ in price, so `OrderPart.send_due` asks `rung_prices` and hands each rung's price to `OrderPart.order`, which puts it over whatever the pricing set. It is the one execution that does this, so `OrderPart` checks for it by type rather than every execution gaining a method for it.

## Why it needs prices

It reads no quotes, but it needs the instrument's tick size to round its rungs, and the plan remembers a tick size only for an order that needs prices. Today's ladder rounds with the tick size the brokers agree on, which is the same number.

## Refusing too small a quantity

Today's ladder refuses before recording anything. A plan reads the quantity only when the order is sent, after the parent is recorded, so the refusal leaves an abandoned parent behind (`a_plan_ladder_needs_a_quantity_for_every_rung`).
