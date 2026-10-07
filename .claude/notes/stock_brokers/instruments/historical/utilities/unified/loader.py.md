# loader.py

## Why the intraday statements carry a time bound

`unified.price_history` and every `<broker>.price_history` are hypertables with one-month chunks reaching back to 2005, so a statement with no condition on `"time"` makes PostgreSQL plan and probe every chunk, even when the rows it wants sit in a few of them. Three statements in `IntradayLoader` ran that way, and on 2026-10-07 the first full intraday load rebuilt about 3 instruments a second, which put one interval at nearly eight hours and the fifteen intervals at well over a week.

| Statement | Change | One instrument, before | After |
|---|---|---:|---:|
| Gap-fill insert, the "missing whole day" test | `not exists` per candidate bar, unbounded, replaced by `not in` over the days the instrument already has from one day before `start` | 31.9 s (BSE RELIANCE, `30minute`, 12,563 bars filled) | 0.3 s |
| `intraday_agreement` | Both tables bounded by the gap-fill broker's earliest bar | 190 ms | 20 ms |
| The source span update in `rebuild` | Bounded by the source's earliest bar at the broker | 78 ms | 4 ms |

The gap-fill rewrite was checked by running both forms inside one rolled-back transaction on the same instrument: both wrote 12,563 bars, and the table afterwards held the same 15,696 bars with the same sum of closes. After all three changes the backfill went from 500 instruments every 170 seconds to 500 every 50 seconds on `240minute`, and a full rebuild of the 30 NSE and BSE listings of 15 large stocks at `15minute` took 69.5 seconds where the old code took 538 seconds for 30 at `30minute`.

## Why only lower bounds

The candle downloaders keep writing while a load runs, and a broker can add bars after `refresh_sources` read its `latest_bar_time`. An upper bound at that time would leave those newest bars out of the agreement count and out of `loaded_latest`. A lower bound alone already skips every older chunk, and there are no chunks after today to skip.

## Why the missing-day subquery starts a day before `start`

Every bar the insert considers is at or after `start`, so only days from `start`'s date onward matter. That date's midnight in India is at most a day before `start`, so `start - 1 day` covers every bar that could share a day with a candidate. `NOT IN` is safe here because the subquery's dates come from `"time"`, which is never null, and PostgreSQL runs it once as a hashed subplan rather than once per bar.
