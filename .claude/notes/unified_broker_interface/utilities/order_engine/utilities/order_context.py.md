# Notes on `unified_broker_interface/utilities/order_engine/utilities/order_context.py`

## Why a context rather than changing every pricing

Stage 5a lets a plan's orders trade different instruments, as a basket's do. Every pricing, execution, trigger, guard and modifier was written against the plan order and asks it for `view`, `tick_size`, `parent.instrument_id` or `parent.body`, all of which describe the parent's instrument. Rather than give each of them an instrument argument, `OrderPart.context` hands them this object, which answers those questions for the order's own instrument and body, so the classes only had to read `instrument_id` and `body` from it instead of from the parent.

## Why it hands the parent's instrument on unchanged

For an order on the parent's own instrument every request goes to the plan order as it did before the context existed, with the same arguments. That kept all 367 recorded scenarios unchanged apart from a new `instrument_id` on each leg of a multi-order answer, and keeps the example programs' stand-in plan orders working without an instrument argument on `place_leg`.

## Tick sizes

A tick size is remembered when the plan is placed: the parent's own in `tick_size`, as before, and every other priced order's in `tick_sizes`. An instrument with none remembered falls back on the parent's, which is what `PlanOrder.view` already did for a watched instrument, so a trigger on another instrument still reads its last price.

## The placement property

It is a property rather than an attribute so a stand-in plan order without a placement can still build a context; only the option model asks for it.

## lot_size (2026-10-05)

Moved here from `ParticipationExecution` so the timed slices, the iceberg's randomised slices, book-depth strikes and the held pieces of a Using join all round to the same lot: the chosen broker's, or before any is chosen the largest any broker lists.
