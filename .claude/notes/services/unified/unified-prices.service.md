# unified-prices.service

## Why the timeout is six hours

The timeout was four hours, sized for the first `factors` run over every instrument, which is thousands of Yahoo requests at about one a second. On 2026-10-07 the job, still loading only daily bars, took 3 hours 44 minutes: the daily load 1 hour 40 minutes, corrections 27 minutes, the second load 2 minutes, factors 16 seconds and verify 1 hour 34 minutes.

From the same day the job also loads the fifteen intraday intervals. Once the first full load of each interval is in, a run rebuilds only instruments with new bars, and only from three days before the newest bar already seen. A day's change was a few thousand series per broker at `15minute` on 2026-10-07, but there was no measured run of the incremental intraday loads when the limit was set, so it was first raised to twelve hours as a ceiling to leave room.

On 2026-10-28 the job moved from 08:30 to 02:00 IST, and `verify` moved out of it to midnight, because a job running into market hours kept the database disk busy enough that the live tick writers lost ticks. Twelve hours from 02:00 would run to 14:00, through the morning's trading, so the ceiling is six hours, ending the job by 08:00, before the 08:25 feed restarts and the 09:00 pre-open. A run stopped by it loses nothing, because each instrument is written in its own transaction and the next night resumes where the sources say it should. If the intraday loads regularly hit the limit, the cure is a faster load or an earlier start, not a later end.
