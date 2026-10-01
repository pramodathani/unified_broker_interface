# Notes on `unified_broker_interface/utilities/order_engine/utilities/daily_execution.py`

## Why an execution rather than a Repeat join

The design draws the daily stop as a Repeat with `every_trading_day_at`. A Repeat is read into one copy per run, and a daily stop runs for up to 365 days, so it would hold a copy per trading day. The stop is really one order the exchange keeps ending, and an execution that sends it again each morning keeps it one part with one path, the way a TWAP sends its slices. The offline scenarios `a_plan_daily_stop_*` send the same requests as today's `a_daily_stop_*`.

## The rules kept

Arming at `arm_at`, 09:20 by default, after the pre-open settles; not on a day that does not trade; the first morning the next trading day when placed after the time; and, through the native stop's `exit_if_gapped`, a marketable exit instead of a stop when the open has gapped past it. Today's type ends the parent `completed` as soon as it sends a gap exit; a plan ends when that exit fills.

## The day sent on

`armed_on` is in the execution's memory and recorded with the event that sends the order, so a restart the same morning does not send a second stop.
