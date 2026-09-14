# Notes on `stock_brokers/instruments/mapping/wisdom_capital.py`

## `NULL_TICK_SEGMENTS`

Wisdom Capital sends a tick size of `1.0` on every row of `bse_equity_indices` (67 rows on 2026-09-14). BSE index prices move in steps of 0.01, and Wisdom Capital's own MCX index ticks are real rupee figures (0.01, 0.05, 1.0 by instrument), so the BSE constant is a placeholder. `to_broker_fields` stores the tick as `None` for that segment and keeps the lot size. The MCX index ticks are left as sent.

The evidence is in the note on `base.py`.
