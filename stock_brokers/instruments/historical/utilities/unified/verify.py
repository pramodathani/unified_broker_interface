"""
Checks on unified.price_history and its adjustment factors.

Each check returns a `Check(name, passed, detail)`. The general checks hold for every instrument:

- **raw fidelity** - every unified bar equals its source broker's bar exactly;
- **hygiene** - no bar on a day its exchange did not trade, and no daily bar off midnight India time;
- **continuity** - trading days missing inside each instrument's loaded span, as a count;
- **cross-exchange** - dual listed instruments whose NSE and BSE closes disagree by more than a few
  percent on the same day, which is how a series served already adjusted gives itself away;
- **coverage** - per segment, instruments in the master against instruments with bars;
- **query plans** - one instrument over five years, and a one day cross-section, timed.

The known-case checks pin the results to corporate actions whose outcome is known independently:
RELIANCE's 2024 bonus and 2023 Jio Financial demerger against zerodha and dhan, AJMERA's 2026 split
against zerodha, and INDIAGLYCO's factor states.
"""

import time
from collections import namedtuple
from decimal import Decimal

from utilities.configurations import get_postgres
from stock_brokers.instruments.historical.utilities.unified import tables

Check = namedtuple("Check", ["name", "passed", "detail"])

def one(cursor, statement, parameters=()):
    """Run a statement and return its first row."""
    cursor.execute(statement, parameters)
    return cursor.fetchone()

def instrument_id(cursor, exchange, segment, symbol):
    """The unified id of an instrument, or None."""
    row = one(cursor, f"select instrument_id::text from {tables.MASTER} where exchange = %s and segment = %s and symbol = %s",
              (exchange, segment, symbol))
    return row[0] if row else None

def broker_token(cursor, broker, unified_id):
    """A broker's latest token for an instrument, or None."""
    row = one(cursor, f"""
        select broker_token from {tables.BROKER_MAPPINGS}
        where broker = %s and instrument_id = %s order by mapping_date desc limit 1
    """, (broker, unified_id))
    return row[0] if row else None

def broker_close(cursor, broker, token, day):
    """A broker's stored daily close for a token on an India date, or None."""
    row = one(cursor, f"""
        select close from {broker}.price_history
        where instrument_token = %s and "interval" = 'day' and "time" = (%s::timestamp at time zone 'Asia/Kolkata')
    """, (token, day))
    return row[0] if row else None

def adjusted_close(cursor, unified_id, day):
    """The adjusted close of an instrument on an India date, or None."""
    row = one(cursor, f"""
        select close from {tables.ADJUSTED_BARS}(%s, 'day', (%s::timestamp at time zone 'Asia/Kolkata'),
                                                    (%s::timestamp at time zone 'Asia/Kolkata') + interval '1 day')
    """, (unified_id, day, day))
    return row[0] if row else None

def raw_fidelity(cursor):
    """Every unified bar equals the bar its source row names, with any confirmed correction applied."""
    mismatched = 0
    compared = 0
    cursor.execute(f"select distinct broker from {tables.PRICE_HISTORY_SOURCES}")
    for (broker,) in cursor.fetchall():
        row = one(cursor, f"""
            select count(*), count(*) filter (where (p.open, p.high, p.low, p.close, p.volume, p.oi)
                is distinct from (
                    coalesce(round(b.open * r.price_multiplier, 2), b.open),
                    coalesce(round(b.high * r.price_multiplier, 2), b.high),
                    coalesce(round(b.low * r.price_multiplier, 2), b.low),
                    coalesce(round(b.close * r.price_multiplier, 2), b.close),
                    case when r.volume_multiplier is null or r.volume_multiplier = 1 then b.volume
                         else round(b.volume * r.volume_multiplier)::bigint end,
                    b.oi))
            from {tables.PRICE_HISTORY} p
            join {tables.PRICE_HISTORY_SOURCES} s on s.source_id = p.source_id and s.broker = %s
            left join {broker}.price_history b
              on b.instrument_token = s.broker_series and b."interval" = p."interval" and b."time" = p."time"
            left join {tables.CORRECTION_RANGES} r
              on r.broker = s.broker and r.broker_series = s.broker_series and r."interval" = p."interval"
             and p."time" >= r.valid_from and p."time" < r.valid_to
        """, (broker,))
        compared += row[0]
        mismatched += row[1]
    return Check("V1 raw fidelity", mismatched == 0, f"{compared:,} bars compared, {mismatched:,} differ")

def hygiene(cursor, calendar):
    """No bars on non-trading days or off the daily grid."""
    cursor.execute(f"""
        select m.exchange, ("time" at time zone 'Asia/Kolkata')::date, count(*),
               count(*) filter (where ("time" at time zone 'Asia/Kolkata')::time <> '00:00')
        from {tables.PRICE_HISTORY} p join {tables.MASTER} m using (instrument_id)
        where p."interval" = 'day' group by 1, 2
    """)
    non_trading = 0
    off_grid = 0
    for exchange, day, count, off in cursor.fetchall():
        off_grid += off
        if exchange in ("nse", "bse") and not calendar.is_trading_day(exchange, day):
            non_trading += count
    return Check("V8 hygiene", non_trading == 0 and off_grid == 0,
                 f"{non_trading} bars on non-trading days, {off_grid} daily bars off midnight")

def continuity(cursor, calendar):
    """Trading days with no bar inside each instrument's loaded span."""
    cursor.execute(f"""
        select m.exchange, m.symbol, array_agg(("time" at time zone 'Asia/Kolkata')::date order by "time")
        from {tables.PRICE_HISTORY} p join {tables.MASTER} m using (instrument_id)
        where p."interval" = 'day' and m.exchange in ('nse', 'bse') group by m.instrument_id, m.exchange, m.symbol
    """)
    gaps = []
    for exchange, symbol, days in cursor.fetchall():
        present = set(days)
        missing = [day for day in calendar.trading_days(exchange) if days[0] <= day <= days[-1] and day not in present]
        if missing:
            gaps.append((f"{exchange}:{symbol}", len(missing)))
    gaps.sort(key=lambda item: -item[1])
    return Check("V2 continuity", True, f"{len(gaps)} instruments with missing trading days; most: {gaps[:6]}")

def stitching(cursor):
    """INDIAGLYCO on NSE runs across its move from EQ to BE without a missing day."""
    unified_id = instrument_id(cursor, "nse", "nse_equities", "INDIAGLYCO")
    cursor.execute(f"""
        select ("time" at time zone 'Asia/Kolkata')::date, s.broker_series
        from {tables.PRICE_HISTORY} p join {tables.PRICE_HISTORY_SOURCES} s using (source_id)
        where p.instrument_id = %s and p."interval" = 'day'
          and p."time" between '2026-08-28' and '2026-09-04' order by 1
    """, (unified_id,))
    rows = cursor.fetchall()
    series = [row[1] for row in rows]
    passed = any("-EQ" in name for name in series) and any("-BE" in name for name in series) and len(rows) >= 5
    return Check("V2 stitching", passed, ", ".join(f"{day}:{name.split('|')[-1]}" for day, name in rows))

def cross_exchange(cursor):
    """
    Dual listed instruments whose NSE and BSE closes sit at different scales for a month or more.

    A single day apart says little - two exchanges' last trades in a thinly traded stock are often
    5% apart - so the test is on the median ratio over each calendar month with at least ten shared
    days. A series served at a different scale, pre-adjusted and not corrected, fails it for every
    month before the action.
    """
    cursor.execute(f"""
        with months as (
            select n.symbol, date_trunc('month', pn."time") as month,
                   percentile_cont(0.5) within group (order by pb.close / pn.close) as ratio, count(*) as days
            from {tables.MASTER} n
            join {tables.MASTER} b
              on b.exchange = 'bse' and b.symbol = n.symbol and b.segment = replace(n.segment, 'nse_', 'bse_')
            join {tables.PRICE_HISTORY} pn on pn.instrument_id = n.instrument_id and pn."interval" = 'day'
            join {tables.PRICE_HISTORY} pb
              on pb.instrument_id = b.instrument_id and pb."interval" = 'day' and pb."time" = pn."time"
            where n.exchange = 'nse' and pn.close > 0
              and n.segment ~ '_(equities|exchange_traded_funds|investment_trusts)$'
            group by 1, 2
        )
        select symbol, count(*) filter (where abs(ratio - 1) > 0.05), count(*),
               round(min(ratio)::numeric, 3), round(max(ratio)::numeric, 3)
        from months where days >= 10
        group by symbol
        having count(*) filter (where abs(ratio - 1) > 0.05) > 0
        order by 2 desc
    """)
    rows = cursor.fetchall()
    cursor.execute(f"select count(distinct symbol) from {tables.MASTER} where exchange = 'nse'")
    return Check("V12 cross-exchange", not rows,
                 f"{len(rows)} dual listed instruments have a month at a different scale; most: "
                 f"{[(symbol, f'{off}/{months} months', float(low), float(high)) for symbol, off, months, low, high in rows[:10]]}")

def bonus(cursor):
    """RELIANCE's adjusted close before the 2024-10-28 bonus matches zerodha and dhan."""
    unified_id = instrument_id(cursor, "nse", "nse_equities", "RELIANCE")
    adjusted = adjusted_close(cursor, unified_id, "2024-10-25")
    zerodha = broker_close(cursor, "zerodha", broker_token(cursor, "zerodha", unified_id), "2024-10-25")
    dhan = broker_close(cursor, "dhan", f"{broker_token(cursor, 'dhan', unified_id)}|NSE_EQ|EQUITY", "2024-10-25")
    passed = adjusted == Decimal("1327.8500") and zerodha == adjusted and dhan == adjusted
    return Check("V3 bonus", passed, f"adjusted {adjusted}, zerodha {zerodha}, dhan {dhan}, expected 1327.85")

def demerger(cursor):
    """Before 2023-07-20, RELIANCE adjusted over zerodha and over dhan are constants."""
    unified_id = instrument_id(cursor, "nse", "nse_equities", "RELIANCE")
    zerodha_token = broker_token(cursor, "zerodha", unified_id)
    dhan_token = f"{broker_token(cursor, 'dhan', unified_id)}|NSE_EQ|EQUITY"
    detail = []
    passed = True
    for broker, token, broker_factor in (("zerodha", zerodha_token, 0.9532), ("dhan", dhan_token, 0.9078)):
        row = one(cursor, f"""
            select count(*), avg(a.close / b.close), min(a.close / b.close), max(a.close / b.close)
            from {tables.ADJUSTED_BARS}(%s, 'day', '2022-01-01', '2023-07-19') a
            join {broker}.price_history b on b.instrument_token = %s and b."interval" = 'day' and b."time" = a."time"
        """, (unified_id, token))
        count, average, low, high = row
        expected = 0.923 / broker_factor
        spread = float(high - low) if count else None
        ok = bool(count) and abs(float(average) - expected) < 0.002 and spread < 0.003
        passed = passed and ok
        detail.append(f"{broker}: {count} bars, ratio {float(average):.5f} (expected {expected:.5f}), spread {spread:.5f}")
    return Check("V4 demerger", passed, "; ".join(detail))

def split(cursor):
    """AJMERA's adjusted close before its 2026-01-14 split matches zerodha."""
    unified_id = instrument_id(cursor, "nse", "nse_equities", "AJMERA")
    adjusted = adjusted_close(cursor, unified_id, "2026-01-13")
    zerodha = broker_close(cursor, "zerodha", broker_token(cursor, "zerodha", unified_id), "2026-01-13")
    passed = adjusted is not None and zerodha is not None and abs(adjusted - zerodha) <= Decimal("0.05")
    return Check("V5 split", passed, f"adjusted {adjusted}, zerodha {zerodha}")

def factor_states(cursor):
    """INDIAGLYCO's factors are in the states their evidence supports."""
    expected = {
        ("nse", "2025-08-12"): "confirmed",    # once the pre-adjusted NSE series is corrected
        ("bse", "2025-08-12"): "confirmed",    # the BSE series is raw and steps there
        ("nse", "2026-09-02"): "provisional",  # Yahoo has not caught up; raw gap awaiting review
        ("bse", "2026-09-02"): "provisional",
    }
    cursor.execute(f"""
        select m.exchange, f.ex_date::text, f.status from {tables.ADJUSTMENT_FACTORS} f
        join {tables.MASTER} m using (instrument_id)
        where m.symbol = 'INDIAGLYCO' and m.segment in ('nse_equities', 'bse_equities')
    """)
    found = {(exchange, day): status for exchange, day, status in cursor.fetchall()}
    wrong = {key: (found.get(key), status) for key, status in expected.items() if found.get(key) != status}
    return Check("V6 factor states", not wrong, f"found {found}" if not wrong else f"(found, expected): {wrong}")

def coverage(cursor):
    """Per segment: instruments in the master against instruments with daily bars."""
    cursor.execute(f"""
        select m.segment, count(*),
               count(*) filter (where exists (select 1 from {tables.PRICE_HISTORY_SOURCES} s
                                              where s.instrument_id = m.instrument_id and s."interval" = 'day'
                                                and s.status = 'active' and s.loaded_latest is not null))
        from {tables.MASTER} m
        where m.last_seen_date = (select max(last_seen_date) from {tables.MASTER})
          and m.segment ~ '_(equities|exchange_traded_funds|investment_trusts|equity_indices)$'
        group by 1 order by 1
    """)
    rows = cursor.fetchall()
    return Check("V9 coverage", True, "; ".join(f"{segment} {loaded}/{total}" for segment, total, loaded in rows))

def query_plans(cursor):
    """One instrument over five years, and a one day cross-section, timed."""
    unified_id = instrument_id(cursor, "nse", "nse_equities", "RELIANCE")
    started = time.monotonic()
    cursor.execute(f"select count(*) from {tables.ADJUSTED_BARS}(%s, 'day', now() - interval '5 years', now())", (unified_id,))
    series_ms = (time.monotonic() - started) * 1000
    started = time.monotonic()
    cursor.execute(f"""
        select count(*) from {tables.PRICE_HISTORY_ADJUSTED}
        where "interval" = 'day' and "time" = ('2025-06-02'::timestamp at time zone 'Asia/Kolkata')
    """)
    cross_ms = (time.monotonic() - started) * 1000
    return Check("V11 query plans", series_ms < 500 and cross_ms < 2000,
                 f"five year series {series_ms:.0f} ms, one day cross-section {cross_ms:.0f} ms")

# An intraday close within this share of the raw daily close, or of the factor, decides a verdict.
CLASSIFIER_TOLERANCE = 0.03

# A verdict needs at least this many corporate actions behind it.
CLASSIFIER_MINIMUM_EVENTS = 5

def classify_intraday(broker, exchange, interval, resolver=None):
    """
    Whether a broker's stored intraday bars on an exchange are adjusted, unadjusted or mixed.

    For every confirmed factor that moves the price by more than 10%, the broker's last intraday bar
    on the trading day before the ex-date is compared with the raw daily close of that day. A bar
    that matches the raw close was stored unadjusted; one that matches the raw close times the factor
    was adjusted afterwards. The verdict is unadjusted or adjusted only when every event agrees, and
    needs `CLASSIFIER_MINIMUM_EVENTS` events.

    Args:
        broker (str): The broker, for example "dhan".
        exchange (str): "nse" or "bse".
        interval (str): The stored intraday interval name.
        resolver (SeriesResolver | None): A resolver to share.

    Returns:
        Check: passed is True for "unadjusted"; the detail names the verdict and the counts.
    """
    from collections import Counter
    from stock_brokers.instruments.historical.utilities.unified.resolution import SeriesResolver

    resolver = resolver or SeriesResolver()
    connection = get_postgres()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"""
                select instrument_token from {broker}.price_history_progress
                where "interval" = %s and bar_count > 0
            """, (interval,))
            identifiers = [row[0] for row in cursor.fetchall()]
            series_of = {}
            for identifier, found in resolver.resolve(broker, identifiers).items():
                for resolution in found:
                    if resolution.instrument_id and resolution.exchange == exchange:
                        series_of.setdefault(resolution.instrument_id, []).append(identifier)

            cursor.execute(f"""
                select f.instrument_id::text, f.ex_date, f.price_factor from {tables.ADJUSTMENT_FACTORS} f
                join {tables.MASTER} m using (instrument_id)
                where f.status = 'confirmed' and abs(f.price_factor - 1) > 0.1 and m.exchange = %s
            """, (exchange,))
            verdicts = Counter()
            examples = []
            for unified_id, ex_date, factor in cursor.fetchall():
                identifiers_for = series_of.get(unified_id)
                if not identifiers_for:
                    continue
                cursor.execute(f"""
                    select ("time" at time zone 'Asia/Kolkata')::date, close from {tables.PRICE_HISTORY}
                    where instrument_id = %s and "interval" = 'day'
                      and "time" < (%s::timestamp at time zone 'Asia/Kolkata')
                    order by "time" desc limit 1
                """, (unified_id, ex_date))
                raw = cursor.fetchone()
                if raw is None:
                    continue
                day, raw_close = raw
                cursor.execute(f"""
                    select close from {broker}.price_history
                    where instrument_token = any(%s) and "interval" = %s
                      and "time" >= (%s::timestamp at time zone 'Asia/Kolkata')
                      and "time" < ((%s::date + 1)::timestamp at time zone 'Asia/Kolkata')
                    order by "time" desc limit 1
                """, (identifiers_for, interval, day, day))
                bar = cursor.fetchone()
                if bar is None or not raw_close:
                    continue
                ratio = float(bar[0] / raw_close)
                if abs(ratio - 1) <= CLASSIFIER_TOLERANCE:
                    verdicts["unadjusted"] += 1
                elif abs(ratio / float(factor) - 1) <= CLASSIFIER_TOLERANCE:
                    verdicts["adjusted"] += 1
                else:
                    verdicts["neither"] += 1
                if len(examples) < 4:
                    examples.append(f"{ex_date} x{float(factor):.3f} ratio {ratio:.3f}")
    finally:
        connection.close()

    events = sum(verdicts.values())
    if events < CLASSIFIER_MINIMUM_EVENTS:
        verdict = "undecided"
    elif verdicts["unadjusted"] == events:
        verdict = "unadjusted"
    elif verdicts["adjusted"] == events:
        verdict = "adjusted"
    else:
        verdict = "mixed"
    return Check(f"V7 {broker} {exchange} {interval}", verdict == "unadjusted",
                 f"{verdict}: {dict(verdicts)} over {events} events; {examples}")

def run_all(calendar, known_cases=True):
    """
    Run every check.

    Args:
        calendar (TradingCalendar): The trading calendar.
        known_cases (bool): Include the RELIANCE, AJMERA and INDIAGLYCO checks.

    Returns:
        list[Check]: The results.
    """
    connection = get_postgres()
    try:
        with connection.cursor() as cursor:
            checks = [raw_fidelity(cursor), hygiene(cursor, calendar), continuity(cursor, calendar),
                      cross_exchange(cursor), coverage(cursor), query_plans(cursor)]
            if known_cases:
                checks[3:3] = [stitching(cursor), bonus(cursor), demerger(cursor), split(cursor), factor_states(cursor)]
        return checks
    finally:
        connection.close()
