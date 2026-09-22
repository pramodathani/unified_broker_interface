# Unified price history

The [price history](price-history.md) downloaders store each broker's candles under that broker's
own identifier. `unified.price_history` holds the same bars once per
[unified instrument](instrument-mapping.md), under its `instrument_id`, with one broker chosen as the
source for each instrument and interval and nothing averaged between brokers.

Equities, exchange traded funds and investment trusts are stored **unadjusted**, and adjusted on read
from `unified.adjustment_factors`. Everything else - indices, futures, options, bonds - is stored
exactly as the broker served it, since there is nothing to adjust.

The history is built by `bin/unified/instruments/price_history`, run each morning by `unified-prices.timer` at
08:30 Monday to Saturday, into `unified.price_history`, `unified.price_history_sources`,
`unified.price_history_corrections`, `unified.adjustment_factors` and `unified.yahoo_fetch_state`, read
adjusted through `unified.price_history_adjusted` and `unified.adjusted_bars`, with series resolved against
`unified.instruments` and `unified.broker_mappings`. See [Unified scripts](unified-scripts.md) and
[Running it as a service](services.md).

!!! note "When the figures were measured"

    The dates and figures below were measured on the history as it stood on 2026-09-14, 8,831,561 bars.

## Running it

```bash
bin/unified/instruments/price_history daily                  # load, corrections, load, factors --stale-days 14, verify
bin/unified/instruments/price_history load                   # copy new and changed daily bars
bin/unified/instruments/price_history factors                # Yahoo Finance -> adjustment factors (first run: hours)
bin/unified/instruments/price_history verify                 # the checks below
bin/unified/instruments/price_history status                 # last run, bar counts, sources, factors
bin/unified/instruments/price_history load --pilot           # just the pilot instruments
```

Every run applies the mapping and price DDL first, so there is no separate DDL step.

Reading it:

```sql
-- raw, as stored
select * from unified.price_history where instrument_id = $1 and "interval" = 'day';

-- adjusted with every confirmed factor
select * from unified.price_history_adjusted where instrument_id = $1 and "interval" = 'day';

-- adjusted as it would have been on a date: no look-ahead in a backtest
select * from unified.adjusted_bars($1, 'day', '2023-01-01', '2024-01-01', p_known_as_of => '2023-06-30');
```

`adjusted_bars` is a single SQL `SELECT` marked `STABLE`, so PostgreSQL inlines it and the instrument,
interval and time conditions still reach the hypertable's chunk exclusion.

## Why store unadjusted prices

Measured against the stored data on 2026-09-13, the brokers that adjust their history do not agree
with each other. For the Jio Financial demerger of 2023-07-20, zerodha's history uses a factor of
0.9532, dhan and IND Money 0.9078, Yahoo Finance about 0.923. They also adjust at different times, and
a stored copy never picks up an adjustment published after it was downloaded. A table of adjusted
prices from several brokers would therefore store a mix of all of that, with no way to tell which bar
carries which. Stored raw, a factor corrected once corrects every query.

| Broker | Daily bars | Intraday bars | Used as a source |
| --- | --- | --- | --- |
| flattrade | BSE unadjusted from 2020-03; NSE from 2019-12, partly pre-adjusted and corrected | unadjusted | daily and intraday cash; indices as gap-fill |
| wisdom_capital | none | unadjusted, BSE, from 2025-09 | BSE 20, 45 and 180 minute; other BSE intraday as gap-fill |
| zerodha | adjusted | adjusted | indices, back to 2005 |
| dhan | adjusted | appears unadjusted | indices as gap-fill; intraday once classified |
| indmoney, fyers | adjusted | - | no |
| shoonya | inconsistent, even within one series | inconsistent | no |

## Undoing flattrade's own adjustments

flattrade's BSE daily bars have been raw in every case checked, but its NSE daily bars are raw across
some corporate actions and already adjusted across others - prices only, volume left as traded. Before
PIDILITIND's 1:1 bonus of 2025-09-23 its NSE daily close is 1,519.0, where the BSE close is 3,037.75 and
flattrade's own last NSE 15 minute bar of that day closed at 3,036.4. On the full load of 2026-09-13,
437 of 2,438 instruments listed on both exchanges had at least one month in which the two closes
differed by more than 5%.

```bash
bin/unified/instruments/price_history corrections                # detect, store, and flag changed instruments
bin/unified/instruments/price_history load                       # rebuild them with the corrections applied
bin/unified/instruments/price_history factors --stale-days 14    # their Yahoo events, now with a step to match
```

[`CorrectionBuilder`][stock_brokers.instruments.historical.utilities.unified.corrections.CorrectionBuilder]
records in `unified.price_history_corrections` the multiplier that undoes each adjustment, per
broker series, and the loader multiplies the served prices back, rounded to the paisa. Detection always
reads the prices as flattrade served them, so an applied correction never hides the adjustment it
undoes. Two references are exact enough to confirm a correction automatically:

| Method | Reference | Covers |
| --- | --- | --- |
| `cross_exchange` | the BSE/NSE close ratio steps; the series that did not jump on the ex-date is the adjusted one | instruments on both exchanges, from 2020 |
| `intraday` | the ratio of the day's last raw 15 minute bar to the daily close steps | any instrument, from September 2025 |
| `yahoo_event` | Yahoo lists a split and the series shows no step - also what a phantom event looks like | stored provisional, never applied |

A step is confirmed only when it lands within 1.5% of a simple ratio with numbers up to ten and has held
for three sessions after the ex-date; until then it is provisional. When an instrument's confirmed
corrections change, its Yahoo split events rejected against the old prices are deleted and it is made
due for a new fetch. On the pilot this turned INDIAGLYCO's NSE bonus of 2025-08-12, PIDILITIND's bonus
and TATAINVEST's 10:1 split from rejected into confirmed factors, and found a PGIL bonus of 2024-01-05
that nobody had looked for.

## Sources and resolution

Each broker series is resolved to an instrument once, as a whole
([`SeriesResolver`][stock_brokers.instruments.historical.utilities.unified.resolution.SeriesResolver]),
from the identifier's own exchange and segment
([`series_context`][stock_brokers.instruments.historical.base.BrokerCandles.series_context]) and, in
order of strength, the broker's own mapping, other brokers' mappings of the same exchange token, and
the trading symbol. On 2026-09-13 all 8,431 flattrade daily series resolved: 7,875 through flattrade's
own mapping, 339 through the exchange token (BE series flattrade's mapping skips), and 227 through the
symbol.

Several things the resolver has to see through are artefacts of the mapping, and worth knowing about
when reading `unified.instruments`:

- On 2026-08-12 only zerodha's file was mapped, so its exchange traded funds and bonds were filed as
  `uncategorised` for that one day, under identities that exist on no other date.
- flattrade's file keeps stale rows under old symbols beside the current ones on the same token
  (ITETFADD beside ITADD on 17207).
- A renamed company is two instruments, because the symbol is part of an instrument's identity, so its
  series is split at the rename.

The source policy
([`sources_for`][stock_brokers.instruments.historical.utilities.unified.sources.sources_for]) names one
primary broker per instrument and interval. That broker's series are stitched together by time, the
series with the most recent bars winning a shared day: INDIAGLYCO's NSE history runs on its EQ token to
2026-09-01 and its BE token from 2026-09-02. A gap-fill broker supplies only days the primary has no
bar for, and only after its bars agree with the primary's on at least 99.5% of shared days. That check
is what keeps flattrade's BSE index bars out: they are stamped a day late, so its SENSEX close on any
date is zerodha's close of the day before.

Bars are dropped when their exchange did not trade that day
([`TradingCalendar`][stock_brokers.instruments.historical.utilities.unified.calendar.TradingCalendar]),
when they are off the interval's grid, or when their high and low do not contain the open and close.

## Intraday bars

```bash
bin/unified/instruments/price_history load --interval 15minute --pilot
```

Intraday history is two orders of magnitude larger than daily - flattrade stores some 300 million
intraday bars, wisdom_capital 60 million - so
[`IntradayLoader`][stock_brokers.instruments.historical.utilities.unified.loader.IntradayLoader] never
brings bars into Python. Each instrument is rebuilt in SQL, from three days before the newest bar its
sources had seen, or over its whole history when a source is new or its history grew backwards.

Two brokers' intraday bars for the same quarter hour differ slightly even when neither is wrong, since
each builds them from its own tick stream: across the pilot's BSE 15 minute bars, flattrade and
wisdom_capital closes agree within 0.05% on 88-97% of bars and within 1% on 97-100%, the illiquid ones
lowest. The intraday gap-fill check is therefore 1% on 95% of shared bars - loose enough for tick
noise, and still failing any series that was adjusted, which misses by a whole factor.

!!! warning "Loaded by hand, and not yet for everything"

    The daily timer loads only daily bars. Loading every intraday interval for every instrument copies
    hundreds of millions of rows, and should wait until the database volume is known to have room.

Whether dhan's intraday bars can fill NSE gaps is decided by the classifier,
[`classify_intraday`][stock_brokers.instruments.historical.utilities.unified.verify.classify_intraday]:
for every confirmed factor of more than 10%, the broker's last bar before the ex-date is compared with
the raw daily close. Every bar matching the raw close makes the series unadjusted; every bar matching
the adjusted close makes it adjusted; anything else is mixed.

## Adjustment factors

[`FactorBuilder`][stock_brokers.instruments.historical.utilities.unified.factors.FactorBuilder] compares
Yahoo Finance's split-adjusted `Close` with the stored raw close. Their ratio is 1 after the last
corporate action and steps at every action before it. Steps are matched to Yahoo's listed split events;
the result for the pilot:

| Instrument | Ex-date | Kind | Factor | Status | Why |
| --- | --- | --- | --- | --- | --- |
| RELIANCE | 2024-10-28 | split (1:1 bonus) | 0.5 | confirmed | Yahoo event and step agree |
| RELIANCE | 2023-07-20 | demerger | 0.923 | confirmed (manual) | step in Close, no event, raw price fell the same; recorded by hand |
| RELIANCE | 2020-05-13 | unclassified | 0.9906 | provisional | the rights issue Yahoo adjusts for |
| AJMERA | 2026-01-14 | split (5:1) | 0.2 | confirmed | Yahoo event and step agree |
| INDIAGLYCO (BSE) | 2025-08-12 | split (1:1 bonus) | 0.5 | confirmed | Yahoo event and step agree |
| INDIAGLYCO (NSE) | 2025-08-12 | split (1:1 bonus) | 0.5 | confirmed | once flattrade's pre-adjustment of the NSE series is corrected |
| INDIAGLYCO | 2026-09-02 | unclassified | 0.21 | provisional | raw price gap Yahoo has not caught up with; dhan implies 0.2024 |

Only a split Yahoo lists, and the stored prices step at, is confirmed automatically. A step Yahoo lists
nothing for is stored as `unclassified` and provisional, because a demerger, a rights issue - Yahoo
adjusts Close for those as well - and an inconsistency in either price series all look the same. On the
first full build a rule that confirmed such steps as demergers when the raw price fell alike confirmed
426 of them, most of them rights issues such as UPL's of 2024-11-26; they were turned back into
provisional rows. Demergers are confirmed by hand, as RELIANCE's is.

Only `confirmed` factors are applied. `provisional` rows wait for a person, who confirms one by setting
its status, or adds a `manual` row, which the builder never overwrites. `rejected` rows are kept so a
rebuild cannot bring back an event that was looked at and found not to apply.

## Checks

`bin/unified/instruments/price_history verify` runs:

| Check | Pass condition |
| --- | --- |
| V1 raw fidelity | every unified bar equals its source broker's bar exactly, times any confirmed correction |
| V2 stitching, continuity | INDIAGLYCO runs across EQ to BE; missing trading days reported |
| V3 bonus | RELIANCE adjusted close on 2024-10-25 is 1327.85, equal to zerodha and dhan |
| V4 demerger | before 2023-07-20, RELIANCE adjusted over zerodha and over dhan are constant |
| V5 split | AJMERA adjusted close on 2026-01-13 within 0.05 of zerodha |
| V6 factor states | INDIAGLYCO's factors in the states above |
| V8 hygiene | no bars on non-trading days or off the daily grid |
| V9 coverage | per segment, instruments with bars against instruments in the master |
| V11 query plans | a five year series and a one day cross-section, timed |
| V12 cross-exchange | dual listed instruments whose NSE and BSE closes agree; what remains after corrections |

A second `load` or `factors` run over unchanged data changes no rows.
