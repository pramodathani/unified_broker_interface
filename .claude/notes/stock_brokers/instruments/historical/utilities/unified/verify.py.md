# verify.py

## Why V1 raw fidelity compares only daily bars

V1 joins every unified bar to the broker bar it came from. On 2026-10-07 that was 14,833,010 daily bars and took about an hour and a half of the morning job. From the same day the daily job loads all fifteen intraday intervals as well, which is on the order of a hundred times more bars, so the check left unfiltered would run for days. Every other check already reads `"interval" = 'day'`, so V1 now does the same.

Intraday bars lose less by going unchecked here than it might seem. They are copied by one `INSERT ... SELECT` straight from the broker's table, with no Python in between, and they carry no corrections, which are the part of V1 most likely to catch a fault. A sampled intraday fidelity check, over the last few days only, would be the way to add coverage back without the cost.

## Why V12 needs three months in a row

V12 failed every night from at least 2026-10-26 with 155 dual listed instruments. Sorted by the longest run of months whose median BSE to NSE close ratio was more than 5% from 1, on 2026-10-29: 114 had only one or two such months, mostly thinly traded stocks in 2020 such as 3PLAND (0.66 to 0.88 in months of 1 to 10 shared days) and 21STCENMGM, whose ratio was otherwise 1.00; 41 had three or more in a row, which is what a series served at a different scale looks like, since it is off for every month before the corporate action. `CROSS_EXCHANGE_RUN` is therefore 3, which takes V12 from 155 failures to 41 on the same data. The 41 are real: series still served at a different scale, from corrections left provisional, corrections the detector missed (KANANIIND's ratio swings between 1.80 and 2.17 month to month), or confirmed corrections that leave a gap (AHLEAST at 1.07 after its 5/7 BSE correction).
