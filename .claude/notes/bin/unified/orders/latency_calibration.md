# Notes on `bin/unified/orders/latency_calibration`

The script is thin; the logic is in `LatencyCalibration` and `BrokerLatency` so `test_runs/execution_costs` can check it against the stand-in database.

## Why it shares a unit with `execution_costs`

It must run after the night's measurement has been written, or it would calibrate on yesterday's table. Giving it its own timer a few minutes later would only work as long as the measurement finished in time. Instead `unified-execution-costs.service`, a oneshot unit, has two `ExecStart=` lines, which systemd runs in order and stops after the first failure. So the calibration always reads tonight's rows, and is skipped on a night the measurement failed.

## Exit codes

It exits 0 when no broker had enough legs, unlike `margin_calibration`, which exits 1 when no broker could be measured. Too few legs is the normal state for weeks after the measurement starts and for any broker that is rarely chosen; failing the unit every night for it would hide real failures.

## Bootstrap line

As in `execution_costs`, the usual comment above `sys.path.insert` is left out under the no-comments rule.
