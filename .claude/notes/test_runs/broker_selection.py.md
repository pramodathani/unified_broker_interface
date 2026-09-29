# Notes on `test_runs/broker_selection.py`

The suite uses the user's table of 2026-09-29 as its fixture, so its expected orderings are the ones production sees on the first day. The expected lists were worked out by hand from the ranking rules before the suite was first run, not copied from the selector's output.

`FixedDaySelector` fixes the share of the session that has passed, because the pacing reads the clock and the orderings would otherwise depend on when the suite is run.

The table's loading is tested by replacing `utilities.configurations.get_postgres` for the duration of one call, the same way the order suites replace `blueprint_base.get_cache`. The Lua scripts are not run here, because the stand-in Redis has no Lua; the rate window's stand-in in `redis_stand_ins.py` mirrors the script, and both scripts were checked against the live Redis when they were written.
