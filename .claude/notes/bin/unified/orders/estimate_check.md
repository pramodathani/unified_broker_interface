# Notes on `bin/unified/orders/estimate_check`

The script only reads and has no timer, because nothing acts on its output: it is a report for a person deciding whether the estimate can be trusted, or whether the impact coefficient needs fitting. It is worth running after a few weeks of new measurements and after any change to `unified.impact_coefficients`.

It does not fit the coefficient. Fitting needs legs larger than the visible book, and there were none when it was written; the `beyond book` column shows when there are. Fitting would then be a separate, writing script, in the pattern of `latency_calibration`.

As in the other new scripts, the usual comment above `sys.path.insert` is left out under the no-comments rule.
