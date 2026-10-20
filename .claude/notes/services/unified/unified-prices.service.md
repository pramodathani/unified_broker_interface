# unified-prices.service

## Why the timeout is twelve hours

The timeout was four hours, sized for the first `factors` run over every instrument, which is thousands of Yahoo requests at about one a second. On 2026-10-07 the job, still loading only daily bars, took 3 hours 44 minutes: the daily load 1 hour 40 minutes, corrections 27 minutes, the second load 2 minutes, factors 16 seconds and verify 1 hour 34 minutes.

From the same day the job also loads the fifteen intraday intervals. Once the first full load of each interval is in, a morning's run rebuilds only instruments with new bars, and only from three days before the newest bar already seen. A day's change was a few thousand series per broker at `15minute` on 2026-10-07, but there was no measured run of the incremental intraday loads when the limit was set. Twelve hours is a ceiling chosen to leave room, not an estimate. A run stopped by it loses nothing, because each instrument is written in its own transaction and the next morning resumes where the sources say it should; only the verify at the end is lost. Lower it once a few mornings have shown the real duration.
