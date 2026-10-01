# Notes on `unified_broker_interface/utilities/order_engine/utilities/front_loaded_execution.py`

## Why it is so short

Everything but the weights is in `TimedSlicesExecution`; see that file's note. The weights copy today's type exactly, so the preset sends what the type sends.
