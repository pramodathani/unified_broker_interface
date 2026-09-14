"""
Derive split, bonus and demerger factors from Yahoo Finance and the stored raw prices.

For each instrument stored unadjusted, the ratio `q = Yahoo Close / raw close` is taken on every day
both have. Yahoo's Close is adjusted and the raw close is not, so q is 1 after the last corporate
action and steps down at each action going back in time: RELIANCE's q is 1 from 2024-10-28, 0.5
before that bonus, and 0.4615 before the 2023-07-20 demerger of Jio Financial, whose factor of about
0.923 Yahoo builds into Close without ever listing it as an event.

**Steps.** q is walked from the newest day back. A move away from the current level counts as a step
only when it holds for `PERSISTENCE` trading days, which passes over Yahoo's one-day bad prints
(2025-03-18 across much of the market; NIFTYBEES for two days in December 2019). The tolerance widens
for low prices, where Yahoo's rounding of the adjusted price to two decimals is a larger share of it.
A step's size is the ratio of the median q on either side of it.

**Classification.** Each step is matched to a listed Yahoo event within `MATCH_WINDOW` trading days:

- a step equal to the event's factor confirms a `split` at the exact ratio;
- a step below it confirms the split and adds a provisional `unclassified` row for the remainder;
- a step with no event is `unclassified` and provisional, with a note of whether the raw close fell by
  about the same amount. Demergers land here, but so do rights issues - Yahoo adjusts Close for those
  too - and inconsistencies in either series; across the first full build, 426 such steps met the
  old test for a demerger, most of them rights issues (UPL, SUZLON, PNBHOUSING) or whole ratios left
  over from a double adjustment (NAZARA's 0.5, RHETAN's 0.1). A person confirms a demerger.

Only listed split events are therefore confirmed automatically.

A listed event with no step anywhere inside the stored history is `rejected`, because applying it
would be wrong for these stored prices whatever the reason. Usually the stored prices already include
it: INDIAGLYCO's 1:1 bonus of 2025-08-12 was real, and its BSE series steps there, but flattrade's NSE
series for it was served already halved before that date, so on NSE there is nothing left to apply.
Events from before the stored history cannot be checked and are stored provisional.

A rebuild replaces the derived rows for an instrument: derived rows it no longer produces are
deleted, so a step that moves - when a hole in the bars is filled - is not applied twice.

**Raw gaps.** An overnight move in the raw close beyond `RAW_GAP` with no factor near it is recorded
as a provisional `raw_gap` row for a person to look at, with the evidence gathered: the ratio, the
nearest simple fraction, whether the series changed token that day, and the factor dhan's re-adjusted
history implies. This is how an action Yahoo has not caught up with surfaces - INDIAGLYCO on 2026-09-02.

Rows a person set (`source = 'manual'`) are never touched, and `rejected` rows are never revived.
"""

import json
from fractions import Fraction
from statistics import median

from stock_brokers.instruments.historical.utilities.unified.yahoo import (MINIMUM_COVERAGE, YahooClient,
                                                                          coverage, ticker_forms)
from stock_brokers.instruments.mapping.utilities.segments import ADJUSTABLE_SEGMENTS
from utilities.configurations import get_logger, get_postgres
from stock_brokers.instruments.historical.utilities.unified import tables

LOGGER = get_logger("unified_prices")

PERSISTENCE = 5
MATCH_WINDOW = 3
SIDE_WINDOW = 20
EVENT_TOLERANCE = 0.01
DEMERGER_RANGE = (0.5, 0.98)
DEMERGER_GAP_TOLERANCE = 0.05
RAW_GAP = 0.35
# q at the newest days must be within this of 1, or the ticker is not this instrument.
LATEST_LEVEL_TOLERANCE = 0.02

def tolerance(raw_close, level):
    """
    How far q may wander from its level without being a move, for a given price.

    Args:
        raw_close (float): The raw close that day.
        level (float): The current level of q.

    Returns:
        float: A relative tolerance.
    """
    adjusted = max(raw_close * level, 0.01)
    return 0.003 + 0.01 / adjusted

def find_steps(days, ratios, raw_closes):
    """
    The persistent level changes in q, newest first.

    Args:
        days (list[datetime.date]): Overlap dates, oldest first.
        ratios (list[float]): q on each date.
        raw_closes (list[float]): The raw close on each date.

    Returns:
        list[dict]: Each with "index" (of the first day at the newer level), "ex_date", "step" (older
            level over newer level) and "dispersion".
    """
    steps = []
    level = ratios[-1]
    boundary = len(days)
    position = len(days) - 1
    while position >= PERSISTENCE:
        if abs(ratios[position] / level - 1) <= tolerance(raw_closes[position], level):
            position -= 1
            continue
        window = ratios[position - PERSISTENCE + 1:position + 1]
        candidate = median(window)
        persistent = all(abs(value / level - 1) > tolerance(raw_closes[position], level) for value in window)
        consistent = all(abs(value / candidate - 1) <= tolerance(raw_closes[position], candidate) for value in window)
        if not (persistent and consistent):
            position -= 1
            continue
        newer = ratios[position + 1:min(position + 1 + SIDE_WINDOW, boundary)]
        older_start = position
        while older_start > 0 and position - older_start < SIDE_WINDOW and \
                abs(ratios[older_start - 1] / candidate - 1) <= tolerance(raw_closes[older_start - 1], candidate):
            older_start -= 1
        older = ratios[older_start:position + 1]
        newer_level = median(newer) if newer else level
        older_level = median(older)
        dispersion = max(abs(value / older_level - 1) for value in older)
        steps.append({
            "index": position + 1,
            "ex_date": days[position + 1],
            "step": older_level / newer_level,
            "dispersion": dispersion,
        })
        boundary = position + 1
        level = older_level
        position -= PERSISTENCE
    return steps

def exact_ratio(value):
    """
    A split ratio as shares after and before.

    Args:
        value (float): Yahoo's ratio, for example 2.0 or 0.3.

    Returns:
        tuple[int, int]: (shares_after, shares_before), for example (2, 1) or (3, 10).
    """
    # A consolidation's ratio is below one and can be small enough, 0.001, to round to 0/1 if
    # approximated directly, so it is approximated through its inverse.
    if value >= 1:
        fraction = Fraction(value).limit_denominator(100)
        return fraction.numerator, fraction.denominator
    fraction = Fraction(1 / value).limit_denominator(100)
    return fraction.denominator, fraction.numerator

class FactorBuilder:
    """
    Builds unified.adjustment_factors for the instruments stored unadjusted.

    Attributes:
        connection: The psycopg2 connection.
        yahoo (YahooClient): Paced Yahoo access.
        counts (dict): What was derived, for the run summary.
    """

    def __init__(self, yahoo=None):
        """
        Prepare a build.

        Args:
            yahoo (YahooClient | None): A client to share, or None to build one.

        Returns:
            None: This function returns nothing.
        """
        self.connection = get_postgres()
        self.yahoo = yahoo or YahooClient()
        self.counts = {}

    def count(self, key):
        """Add one to a summary count."""
        self.counts[key] = self.counts.get(key, 0) + 1

    def instruments(self, instrument_ids=None):
        """
        The instruments with unadjusted daily bars, and what is needed to find them on Yahoo.

        Args:
            instrument_ids (set[str] | None): Restrict to these, or None for all.

        Returns:
            list[tuple]: (instrument_id, exchange, symbol, scrip_code, listed_on_nse), scrip_code None for NSE.
        """
        segments = [f"{exchange}_{segment}" for exchange in ("nse", "bse") for segment in ADJUSTABLE_SEGMENTS]
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select m.instrument_id::text, m.exchange, m.symbol,
                       (select b.broker_token from {tables.BROKER_MAPPINGS} b
                        where b.instrument_id = m.instrument_id and b.broker = 'dhan' and m.exchange = 'bse'
                        order by b.mapping_date desc limit 1),
                       exists (select 1 from {tables.MASTER} n
                               where n.exchange = 'nse' and n.symbol = m.symbol
                                 and n.segment = replace(m.segment, 'bse_', 'nse_'))
                from {tables.MASTER} m
                where m.segment = any(%s)
                  and exists (select 1 from {tables.PRICE_HISTORY_SOURCES} s
                              where s.instrument_id = m.instrument_id and s."interval" = 'day'
                                and s.price_basis = 'unadjusted' and s.loaded_latest is not null)
                  and m.symbol not like '%%NSETEST%%'
                  and (%s::text[] is null or m.instrument_id::text = any(%s))
                order by m.exchange, m.symbol
            """, (segments, list(instrument_ids) if instrument_ids else None,
                  list(instrument_ids) if instrument_ids else None))
            return cursor.fetchall()

    def raw_daily(self, instrument_id):
        """
        One instrument's raw daily closes, and the source each came from.

        Args:
            instrument_id (str): The instrument.

        Returns:
            tuple[list, list, list]: Dates, closes and source ids, oldest first.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select ("time" at time zone 'Asia/Kolkata')::date, close, source_id
                from {tables.PRICE_HISTORY}
                where instrument_id = %s and "interval" = 'day' and close > 0
                order by "time"
            """, (instrument_id,))
            rows = cursor.fetchall()
        # End the read transaction: the Yahoo request that follows can take seconds, and an open
        # transaction held across it keeps vacuum from cleaning the tables behind it.
        self.connection.rollback()
        return [row[0] for row in rows], [float(row[1]) for row in rows], [row[2] for row in rows]

    def build(self, instrument_ids=None):
        """
        Fetch, derive and store factors for each instrument.

        Args:
            instrument_ids (set[str] | None): Restrict to these, or None for all.

        Returns:
            dict: Summary counts.
        """
        targets = self.instruments(instrument_ids)
        LOGGER.info("factors: %d instruments", len(targets))
        for position, (instrument_id, exchange, symbol, scrip_code, listed_on_nse) in enumerate(targets, 1):
            try:
                self.build_one(instrument_id, exchange, symbol, scrip_code, listed_on_nse)
            except Exception as error:
                self.connection.rollback()
                self.record_fetch(instrument_id, None, None, "error", str(error)[:500], None, None, None)
                self.count("error")
                LOGGER.exception("factors: %s %s failed", exchange, symbol)
            if position % 100 == 0:
                LOGGER.info("factors: %d of %d, %s", position, len(targets), self.counts)
        return self.counts

    def build_one(self, instrument_id, exchange, symbol, scrip_code, listed_on_nse=False):
        """
        Fetch one instrument from Yahoo, derive its factors and store them.

        Args:
            instrument_id (str): The instrument.
            exchange (str): "nse" or "bse".
            symbol (str): Its trading symbol.
            scrip_code (str | None): Its BSE scrip code.
            listed_on_nse (bool): Whether a BSE instrument is also listed on NSE.

        Returns:
            None: This function returns nothing.
        """
        days, raw_closes, source_ids = self.raw_daily(instrument_id)
        if len(days) < PERSISTENCE * 2:
            self.count("too_little_raw")
            return

        chosen = None
        for ticker, kind in ticker_forms(exchange, symbol, scrip_code, listed_on_nse):
            closes, events = self.yahoo.history(ticker)
            if coverage(closes, days) >= MINIMUM_COVERAGE:
                chosen = (ticker, kind, closes, events)
                break
        if chosen is None:
            self.record_fetch(instrument_id, None, None, "empty", "no ticker form covers the raw history",
                              None, None, None)
            self.count("empty")
            return
        ticker, kind, closes, events = chosen

        overlap = [index for index, day in enumerate(days) if day in closes]
        overlap_days = [days[index] for index in overlap]
        overlap_raw = [raw_closes[index] for index in overlap]
        ratios = [closes[day] / raw for day, raw in zip(overlap_days, overlap_raw)]
        history_start, history_end = min(closes), max(closes)
        last_event = max(events) if events else None

        # The newest day decides, not a median of the last few: an action that went ex yesterday leaves
        # one day at the current level, as PGIL's bonus of 2026-09-11 did.
        latest_level = ratios[-1]
        if abs(latest_level - 1) > LATEST_LEVEL_TOLERANCE:
            self.record_fetch(instrument_id, ticker, kind, "mismatch",
                              f"latest Yahoo/raw ratio {latest_level:.4f}", history_start, history_end, last_event)
            self.count("mismatch")
            return

        rows = self.derive(instrument_id, ticker, overlap_days, overlap_raw, ratios, events)
        rows.extend(self.raw_gaps(instrument_id, exchange, days, raw_closes, source_ids, rows))
        self.store(instrument_id, rows)
        self.record_fetch(instrument_id, ticker, kind, "ok", None, history_start, history_end, last_event)
        self.count("ok")

    def derive(self, instrument_id, ticker, days, raw_closes, ratios, events):
        """
        Turn q's steps and Yahoo's events into factor rows.

        Args:
            instrument_id (str): The instrument.
            ticker (str): The Yahoo ticker used.
            days (list): Overlap dates, oldest first.
            raw_closes (list[float]): Raw closes on those dates.
            ratios (list[float]): q on those dates.
            events (dict): Yahoo's listed events, date to ratio.

        Returns:
            list[dict]: Factor rows.
        """
        rows = []
        steps = find_steps(days, ratios, raw_closes)
        matched_events = set()
        for step in steps:
            index = step["index"]
            window = days[max(0, index - MATCH_WINDOW):min(len(days), index + MATCH_WINDOW + 1)]
            event_date = None
            for day in sorted(events, key=lambda day: abs((day - step["ex_date"]).days)):
                if window[0] <= day <= window[-1]:
                    event_date = day
                    break
            evidence = {"q_before": round(ratios[index - 1], 6), "q_after": round(ratios[index], 6),
                        "raw_close_before": raw_closes[index - 1], "raw_close_after": raw_closes[index]}
            base = {"instrument_id": instrument_id, "ex_date": step["ex_date"], "yahoo_symbol": ticker,
                    "observed_step": step["step"], "observed_dispersion": step["dispersion"]}

            if event_date is not None:
                matched_events.add(event_date)
                # Inside a hole in the raw bars the step can only be seen at the first bar after it,
                # while the event names the day itself: flattrade has no BSE RELIANCE bars from
                # 2024-10-20 to 2024-11-20, across the 2024-10-28 bonus.
                if days[index - 1] < event_date <= days[index]:
                    base["ex_date"] = event_date
                ratio = events[event_date]
                expected = 1 / ratio
                shares_after, shares_before = exact_ratio(ratio)
                residual = step["step"] / expected
                status = "confirmed" if residual <= 1 + EVENT_TOLERANCE else "provisional"
                rows.append(dict(base, kind="split", shares_after=shares_after, shares_before=shares_before,
                                 price_factor=shares_before / shares_after, volume_factor=shares_after / shares_before,
                                 status=status, source="yahoo_split_event", yahoo_event_date=event_date,
                                 yahoo_event_ratio=ratio, evidence=dict(evidence, residual=round(residual, 6))))
                if residual < 1 - EVENT_TOLERANCE:
                    rows.append(dict(base, kind="unclassified", shares_after=None, shares_before=None,
                                     price_factor=residual, volume_factor=1, status="provisional",
                                     source="yahoo_close_ratio", yahoo_event_date=None, yahoo_event_ratio=None,
                                     evidence=dict(evidence, note="remainder after the listed split")))
                continue

            # A step Yahoo lists no event for is a demerger, a rights issue, or an inconsistency in one
            # of the two price series, and prices alone do not say which: UPL's rights issue of
            # 2024-11-26 and RELIANCE's Jio Financial demerger of 2023-07-20 look the same here. So it
            # waits for a person, who confirms a demerger by setting its kind and status.
            raw_move = raw_closes[index] / raw_closes[index - 1]
            demerger_like = (DEMERGER_RANGE[0] <= step["step"] <= DEMERGER_RANGE[1]
                             and abs(raw_move - step["step"]) <= DEMERGER_GAP_TOLERANCE)
            rows.append(dict(base, kind="unclassified", shares_after=None, shares_before=None,
                             price_factor=step["step"], volume_factor=1, status="provisional",
                             source="yahoo_close_ratio", yahoo_event_date=None, yahoo_event_ratio=None,
                             evidence=dict(evidence, raw_move=round(raw_move, 6), raw_price_fell_alike=demerger_like)))

        for event_date, ratio in events.items():
            if event_date in matched_events:
                continue
            shares_after, shares_before = exact_ratio(ratio)
            inside = days[PERSISTENCE] <= event_date <= days[-PERSISTENCE]
            rows.append({"instrument_id": instrument_id, "ex_date": event_date, "kind": "split",
                         "shares_after": shares_after, "shares_before": shares_before,
                         "price_factor": shares_before / shares_after, "volume_factor": shares_after / shares_before,
                         "status": "rejected" if inside else "provisional", "source": "yahoo_split_event",
                         "yahoo_symbol": ticker, "yahoo_event_date": event_date, "yahoo_event_ratio": ratio,
                         "observed_step": None, "observed_dispersion": None,
                         "evidence": {"note": "listed by Yahoo, but Yahoo's Close and the stored prices move "
                                              "together across it: either there was no action, or the stored "
                                              "prices already include it" if inside
                                      else "listed by Yahoo before the stored history begins; not verifiable"
                                      if event_date < days[PERSISTENCE]
                                      else "listed by Yahoo too recently to check against the stored prices"}})
        return rows

    def raw_gaps(self, instrument_id, exchange, days, raw_closes, source_ids, derived):
        """
        Overnight raw moves too large to be trading, with no factor near them.

        Args:
            instrument_id (str): The instrument.
            exchange (str): "nse" or "bse".
            days (list): All raw dates, oldest first.
            raw_closes (list[float]): Raw closes.
            source_ids (list[int]): The source of each bar.
            derived (list[dict]): The rows already derived, which cover gaps near them.

        Returns:
            list[dict]: Provisional raw_gap rows.
        """
        explained = [row["ex_date"] for row in derived if row["status"] != "rejected"]
        rows = []
        for index in range(1, len(days)):
            move = raw_closes[index] / raw_closes[index - 1]
            if 1 - RAW_GAP <= move <= 1 / (1 - RAW_GAP):
                continue
            window = days[max(0, index - MATCH_WINDOW):min(len(days), index + MATCH_WINDOW + 1)]
            if any(window[0] <= day <= window[-1] for day in explained):
                continue
            snapped = Fraction(move).limit_denominator(10)
            evidence = {
                "raw_close_before": raw_closes[index - 1], "raw_close_after": raw_closes[index],
                "move": round(move, 6), "nearest_fraction": f"{snapped.numerator}/{snapped.denominator}",
                "token_changed": source_ids[index] != source_ids[index - 1],
                "dhan_factor": self.dhan_factor(instrument_id, exchange, days[index - 1], raw_closes[index - 1]),
            }
            rows.append({"instrument_id": instrument_id, "ex_date": days[index], "kind": "unclassified",
                         "shares_after": None, "shares_before": None, "price_factor": move, "volume_factor": 1,
                         "status": "provisional", "source": "raw_gap", "yahoo_symbol": None,
                         "yahoo_event_date": None, "yahoo_event_ratio": None, "observed_step": move,
                         "observed_dispersion": None, "evidence": evidence})
        return rows

    def dhan_factor(self, instrument_id, exchange, day, raw_close):
        """
        The factor dhan's adjusted history implies for a day: its close over the raw close.

        Args:
            instrument_id (str): The instrument.
            exchange (str): "nse" or "bse".
            day (datetime.date): The last day before the move.
            raw_close (float): The raw close that day.

        Returns:
            float | None: The ratio, or None when dhan has no bar for the day.
        """
        segment = "NSE_EQ" if exchange == "nse" else "BSE_EQ"
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select p.close from {tables.BROKER_MAPPINGS} b
                join dhan.price_history p
                  on p.instrument_token like b.broker_token || '|' || %s || '|%%'
                 and p."interval" = 'day'
                 and p."time" = (%s::timestamp at time zone 'Asia/Kolkata')
                where b.instrument_id = %s and b.broker = 'dhan'
                order by b.mapping_date desc limit 1
            """, (segment, day, instrument_id))
            row = cursor.fetchone()
        if row is None or row[0] is None:
            return None
        return round(float(row[0]) / raw_close, 6)

    def store(self, instrument_id, rows):
        """
        Upsert derived rows, leaving manual and rejected rows as they are.

        Args:
            instrument_id (str): The instrument.
            rows (list[dict]): The derived rows.

        Returns:
            None: This function returns nothing.
        """
        with self.connection.cursor() as cursor:
            # A date a person has already decided is left to that decision.
            cursor.execute(f"""
                select ex_date from {tables.ADJUSTMENT_FACTORS} where instrument_id = %s and source = 'manual'
            """, (instrument_id,))
            decided = {row[0] for row in cursor.fetchall()}
            rows = [row for row in rows if row["ex_date"] not in decided]
            cursor.execute(f"""
                delete from {tables.ADJUSTMENT_FACTORS}
                where instrument_id = %s and source <> 'manual' and status <> 'rejected'
                  and not (ex_date::text || '|' || kind = any(%s))
            """, (instrument_id, [f"{row['ex_date'].isoformat()}|{row['kind']}" for row in rows]))
            self.counts["stale_deleted"] = self.counts.get("stale_deleted", 0) + cursor.rowcount
            for row in rows:
                cursor.execute(f"""
                    insert into {tables.ADJUSTMENT_FACTORS}
                        (instrument_id, ex_date, kind, shares_after, shares_before, price_factor, volume_factor,
                         status, source, yahoo_symbol, yahoo_event_date, yahoo_event_ratio, observed_step,
                         observed_dispersion, evidence)
                    values (%(instrument_id)s, %(ex_date)s, %(kind)s, %(shares_after)s, %(shares_before)s,
                            %(price_factor)s, %(volume_factor)s, %(status)s, %(source)s, %(yahoo_symbol)s,
                            %(yahoo_event_date)s, %(yahoo_event_ratio)s, %(observed_step)s,
                            %(observed_dispersion)s, %(evidence)s)
                    on conflict (instrument_id, ex_date, kind) do update set
                        shares_after = excluded.shares_after, shares_before = excluded.shares_before,
                        price_factor = excluded.price_factor, volume_factor = excluded.volume_factor,
                        status = excluded.status, source = excluded.source, yahoo_symbol = excluded.yahoo_symbol,
                        yahoo_event_date = excluded.yahoo_event_date, yahoo_event_ratio = excluded.yahoo_event_ratio,
                        observed_step = excluded.observed_step, observed_dispersion = excluded.observed_dispersion,
                        evidence = excluded.evidence, updated_at = now()
                    where {tables.ADJUSTMENT_FACTORS}.source <> 'manual'
                      and {tables.ADJUSTMENT_FACTORS}.status <> 'rejected'
                      and ({tables.ADJUSTMENT_FACTORS}.price_factor, {tables.ADJUSTMENT_FACTORS}.status,
                           {tables.ADJUSTMENT_FACTORS}.evidence)
                          is distinct from (excluded.price_factor, excluded.status, excluded.evidence)
                """, dict(row, price_factor=round(row["price_factor"], 10), volume_factor=round(row["volume_factor"], 10),
                          observed_step=None if row["observed_step"] is None else round(row["observed_step"], 10),
                          observed_dispersion=None if row["observed_dispersion"] is None
                          else round(row["observed_dispersion"], 10),
                          evidence=json.dumps(row["evidence"], default=str)))
                self.count(f"{row['kind']}_{row['status']}")
        self.connection.commit()

    def record_fetch(self, instrument_id, ticker, kind, status, error, history_start, history_end, last_event):
        """
        Record where the Yahoo fetch got to for an instrument.

        Args:
            instrument_id (str): The instrument.
            ticker (str | None): The ticker used.
            kind (str | None): "ticker" or "scrip_code".
            status (str): "ok", "empty", "mismatch" or "error".
            error (str | None): What went wrong.
            history_start (datetime.date | None): Yahoo's first date.
            history_end (datetime.date | None): Yahoo's last date.
            last_event (datetime.date | None): Yahoo's latest listed event.

        Returns:
            None: This function returns nothing.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                insert into {tables.YAHOO_FETCH_STATE}
                    (instrument_id, yahoo_symbol, symbol_kind, last_fetched_at, last_status, last_error,
                     history_start, history_end, last_event_date)
                values (%s, %s, %s, now(), %s, %s, %s, %s, %s)
                on conflict (instrument_id) do update set
                    yahoo_symbol = coalesce(excluded.yahoo_symbol, {tables.YAHOO_FETCH_STATE}.yahoo_symbol),
                    symbol_kind = coalesce(excluded.symbol_kind, {tables.YAHOO_FETCH_STATE}.symbol_kind),
                    last_fetched_at = excluded.last_fetched_at, last_status = excluded.last_status,
                    last_error = excluded.last_error,
                    history_start = coalesce(excluded.history_start, {tables.YAHOO_FETCH_STATE}.history_start),
                    history_end = coalesce(excluded.history_end, {tables.YAHOO_FETCH_STATE}.history_end),
                    last_event_date = coalesce(excluded.last_event_date, {tables.YAHOO_FETCH_STATE}.last_event_date)
            """, (instrument_id, ticker, kind, status, error, history_start, history_end, last_event))
        self.connection.commit()
