# Notes on `170_unified_impact_coefficients.sql`

The table holds the square-root impact model's coefficient Y for each asset class. It sits in the mapping DDL directory beside `unified.margin_rates` because, like that table, it is a small hand-maintained reference table that the daily mapping run re-applies.

The seed of 1.0 is the textbook value: studies of equity, futures and other markets find Y of order 1, commonly between about 0.5 and 1. It was chosen on 2026-10-06, when the user asked for the model to be built before any order had been large enough to fit it. `fitted_at` stays `NULL` for a textbook value; a fitting script, when one exists, sets it. The seed uses `ON CONFLICT DO NOTHING`, so a fitted or hand-edited value is never overwritten by the morning re-apply.
