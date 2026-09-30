# Notes on `unified_broker_interface/utilities/order_engine/utilities/preset_expander.py`

## Why a preset expands into slot values written as a caller would write them

Expanding into the same JSON a caller writes by hand means the plan reader checks presets and hand-written values with one set of rules and one set of messages. A problem in a preset's value is reported under the preset's path, so the caller sees which preset it came from.

## Why each preset keeps its type's setting names

A caller moving from `{"type": "market_if_touched", "trigger_price": 995}` to a plan writes `{"market_if_touched": {"trigger_price": 995}}` and nothing else changes. That is what lets the switch-over stage route an old type name to its preset without callers noticing.

## Why the hidden stop's backstop is refused for now

The backstop is a second order resting beside the engine-side stop, cancelled before the exit is sent. That needs the Either join with `cancel_before_send`, which is step 2b, so `backstop_price` is reported as a setting the preset does not take yet.
