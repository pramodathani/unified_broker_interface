# verify.py

## Why V1 raw fidelity compares only daily bars

V1 joins every unified bar to the broker bar it came from. On 2026-10-07 that was 14,833,010 daily bars and took about an hour and a half of the morning job. From the same day the daily job loads all fifteen intraday intervals as well, which is on the order of a hundred times more bars, so the check left unfiltered would run for days. Every other check already reads `"interval" = 'day'`, so V1 now does the same.

Intraday bars lose less by going unchecked here than it might seem. They are copied by one `INSERT ... SELECT` straight from the broker's table, with no Python in between, and they carry no corrections, which are the part of V1 most likely to catch a fault. A sampled intraday fidelity check, over the last few days only, would be the way to add coverage back without the cost.
