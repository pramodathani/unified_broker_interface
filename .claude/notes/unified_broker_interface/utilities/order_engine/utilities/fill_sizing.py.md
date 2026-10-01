# fill_sizing.py

## Why a base class (2026-10-01)

`FillRatio` and `FillDelta` differ only in how they work out the wanted size; the lot lookup at the chosen broker and the half-up rounding to whole lots are the same mechanism, so they live here. `check` is here too so `PlanOrder.run` can ask any sizing to check itself before the parent is recorded, which only `FillDelta` uses.
