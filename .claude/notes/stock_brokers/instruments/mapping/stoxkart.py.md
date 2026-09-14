# Notes on `stock_brokers/instruments/mapping/stoxkart.py`

## `NULL_TICK_SEGMENTS`

Stoxkart sends a tick size of `1.0` on every row of `nse_equity_indices` (116 rows on 2026-09-14) and `bse_equity_indices` (29 rows), whatever the index. Stored prices show that NSE indices move in steps of 0.05 and BSE indices in steps of 0.01, so the figure is neither rupees nor paise, and `to_broker_fields` stores the tick as `None` for those two segments. The lot size is kept.

Stoxkart's MCX and NCDEX index ticks vary by instrument (1, 25, 100) and agree with Kotak's paise figures, so they are real values and are converted with `divide_by_100` in `utilities/rules/stoxkart.yaml` instead.

The evidence for both decisions is in the note on `base.py`.
