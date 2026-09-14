"""
Find where flattrade served a daily series already adjusted, and record the multiplier that undoes it.

flattrade's NSE daily bars are raw across some corporate actions and already adjusted across others,
prices only, volume left as traded. Before PIDILITIND's 1:1 bonus of 2025-09-23 its NSE daily close
is 1,519.0 where its BSE close is 3,038 and its own last NSE 15 minute bar of that day closed at
3,036.4. Stored as served, the unified table would carry adjusted prices under a raw label, and the
adjustment factor for the bonus could never be applied, since nothing in the stored prices steps.

Two references are exact enough to confirm a correction automatically:

- **cross_exchange.** The ratio of the BSE close to the NSE close is 1 on every ordinary day and
  steps where one exchange's series was served at a different scale. Which series to correct is
  decided by what each choice would say both prices did that day - see `cross_exchange`.
- **intraday.** flattrade's intraday bars are raw, so the ratio of a day's last 15 minute bar to that
  day's daily close steps where the daily series was adjusted. Intraday history starts in September
  2025, so this covers recent actions, including those of instruments listed on one exchange only.

A step counts only when it holds for `PERSISTENCE` days on the older side, lands within 1.5% of a
simple ratio with a denominator up to ten, and has held for at least `MINIMUM_NEWER_RUN` days on the newer
side; otherwise the row is kept provisional. PGIL's bonus went ex on 2026-09-11 and has one day on
the newer side, so it waits a few sessions.

A third kind of evidence is recorded but never confirmed: a split Yahoo lists where the series shows
no step at all (`yahoo_event`). That is what a pre-adjusted series looks like, and also what a phantom
event looks like, and nothing in the stored data tells the two apart.

When the confirmed multipliers of a series change, its sources are marked so the next `load` rebuilds
the instrument, the Yahoo split events rejected for it are deleted, and it is made due for a new
Yahoo fetch - with the raw prices restored, those events should now show the step they lacked.
"""

import json
from fractions import Fraction
from statistics import median

from utilities.configurations import get_logger, get_postgres
from stock_brokers.instruments.historical.utilities.unified import tables

LOGGER = get_logger("unified_prices")

BROKER = "flattrade"
INTERVAL = "day"
REFERENCE_INTERVAL = "15minute"

PERSISTENCE = 5
MINIMUM_NEWER_RUN = 3
SIDE_WINDOW = 20
SNAP_TOLERANCE = 0.015
# A ratio this close to 1 is within ordinary disagreement between two prices.
PAIR_TOLERANCE = 0.02
PAIR_ANCHOR_TOLERANCE = 0.15
INTRADAY_TOLERANCE = 0.02
# Steps smaller than these are not looked for: a 1:5 bonus is 1.2, while a rights issue or demerger at
# a few percent is within the noise of two exchanges' closes and of a day's last bar against its close.
MINIMUM_PAIR_STEP = 1.15
# A reading of a pair step in which both prices rose by more than this on the day is not believed.
IMPLAUSIBLE_RISE = 1.25
# A reading reproduces a Yahoo split when its common move is within this of the factor, in log terms,
# and nearer than the other reading by at least the margin. Loose, because across a hole in one series
# the move includes weeks of trading: POWERMECH's 1:1 bonus reads as 0.41 over BSE's 2024 gap.
EVENT_MATCH = 0.3
EVENT_MARGIN = 0.2
MINIMUM_INTRADAY_STEP = 1.08
MERGE_WINDOW_DAYS = 5

def level_steps(values, tolerance, anchor=1.0, anchor_tolerance=None):
    """
    The persistent level changes in a ratio series, walked from the newest value back.

    The newest level is taken to be `anchor`. A series whose newest value, and the median of its last
    `PERSISTENCE` values, are both further than `anchor_tolerance` from it has no steps that can be
    measured, and None is returned. The anchor test is looser than the level tolerance because two
    exchanges' last trades in a thinly traded stock can be several percent apart on any one day.

    Args:
        values (list[float]): The ratio on each day, oldest first.
        tolerance (float): The relative distance within which a value is at a level.
        anchor (float): The level at the newest end.
        anchor_tolerance (float | None): How near `anchor` the newest values must be; `tolerance` when None.

    Returns:
        list[dict] | None: Each step with "index" (first day at the newer level), "older", "newer",
            "newer_run" (days seen at the newer level) and "dispersion"; newest first.
    """
    anchor_tolerance = tolerance if anchor_tolerance is None else anchor_tolerance
    if not values:
        return None
    if abs(values[-1] / anchor - 1) > anchor_tolerance and \
            abs(median(values[-PERSISTENCE:]) / anchor - 1) > anchor_tolerance:
        return None
    steps = []
    level = anchor
    run = 0
    position = len(values) - 1
    while position >= 0:
        value = values[position]
        if abs(value / level - 1) <= tolerance:
            run += 1
            position -= 1
            continue
        if position - PERSISTENCE + 1 < 0:
            break
        window = values[position - PERSISTENCE + 1:position + 1]
        candidate = median(window)
        persistent = all(abs(item / level - 1) > tolerance for item in window)
        consistent = all(abs(item / candidate - 1) <= tolerance for item in window)
        if not (persistent and consistent):
            position -= 1
            continue
        start = position
        while start > 0 and position - start < SIDE_WINDOW and abs(values[start - 1] / candidate - 1) <= tolerance:
            start -= 1
        older_values = values[start:position + 1]
        older = median(older_values)
        newer_values = values[position + 1:position + 1 + min(run, SIDE_WINDOW)]
        newer = median(newer_values) if newer_values else level
        steps.append({"index": position + 1, "older": older, "newer": newer, "newer_run": run,
                      "dispersion": max(abs(item / older - 1) for item in older_values)})
        level = older
        run = PERSISTENCE
        position -= PERSISTENCE
    return steps

def snap(value):
    """
    The simple ratio, denominator up to ten, a multiplier is within `SNAP_TOLERANCE` of.

    Args:
        value (float): The observed multiplier.

    Returns:
        Fraction | None: The ratio, or None when the value is not near a simple one.
    """
    # The smallest denominator that fits wins: IRB's NSE series was served at a hundredth of its price,
    # and 100/1 is the reading, not the 599/6 a closest-fraction search lands on.
    # A larger denominator wins only when it fits clearly better: HARDWYN's 13.329 is 40/3, not 27/2.
    inverted = value < 1
    target = 1 / value if inverted else value
    fits = []
    for denominator in range(1, 11):
        numerator = round(target * denominator)
        if numerator > 0:
            error = abs(numerator / denominator / target - 1)
            if error <= SNAP_TOLERANCE:
                fits.append((denominator, error, Fraction(numerator, denominator)))
    if not fits:
        return None
    best_error = min(error for _, error, _ in fits)
    for denominator, error, fraction in fits:
        if error <= max(0.003, 2 * best_error):
            return 1 / fraction if inverted else fraction
    return None

class CorrectionBuilder:
    """
    Builds unified.price_history_corrections for flattrade's daily series.

    Attributes:
        connection: The psycopg2 connection.
        counts (dict): What was found, for the run summary.
    """

    def __init__(self):
        """
        Prepare a build.

        Returns:
            None: This function returns nothing.
        """
        self.connection = get_postgres()
        self.counts = {}

    def count(self, key, amount=1):
        """Add to a summary count."""
        self.counts[key] = self.counts.get(key, 0) + amount

    def instruments(self, instrument_ids=None):
        """
        The instruments stored unadjusted from flattrade daily bars.

        Args:
            instrument_ids (set[str] | None): Restrict to these, or None for all.

        Returns:
            list[tuple]: (instrument_id, exchange, segment, symbol).
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select distinct m.instrument_id::text, m.exchange, m.segment, m.symbol
                from {tables.MASTER} m
                join {tables.PRICE_HISTORY_SOURCES} s
                  on s.instrument_id = m.instrument_id and s.broker = %s and s."interval" = %s
                 and s.price_basis = 'unadjusted' and s.status = 'active' and s.loaded_latest is not null
                where (%s::text[] is null or m.instrument_id::text = any(%s))
                order by m.exchange, m.symbol
            """, (BROKER, INTERVAL, list(instrument_ids) if instrument_ids else None,
                  list(instrument_ids) if instrument_ids else None))
            return cursor.fetchall()

    def served(self, instrument_id):
        """
        An instrument's daily closes exactly as flattrade served them, with the series of each.

        Read from the broker's table through the unified bars' sources, so a correction already
        applied to the stored bars does not hide the adjustment it corrects.

        Args:
            instrument_id (str): The instrument.

        Returns:
            dict: datetime.date to (close as float, broker_series).
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select (p."time" at time zone 'Asia/Kolkata')::date, b.close, s.broker_series
                from {tables.PRICE_HISTORY} p
                join {tables.PRICE_HISTORY_SOURCES} s on s.source_id = p.source_id and s.broker = %s
                join flattrade.price_history b
                  on b.instrument_token = s.broker_series and b."interval" = p."interval" and b."time" = p."time"
                where p.instrument_id = %s and p."interval" = %s and b.close > 0
            """, (BROKER, instrument_id, INTERVAL))
            return {day: (float(close), series) for day, close, series in cursor.fetchall()}

    def intraday_last_closes(self, series):
        """
        The close of the last intraday bar of each day across an instrument's flattrade series.

        Args:
            series (set[str]): The broker series identifiers.

        Returns:
            dict: datetime.date to float.
        """
        with self.connection.cursor() as cursor:
            cursor.execute("""
                select distinct on (day) day, close
                from (select ("time" at time zone 'Asia/Kolkata')::date as day, "time", close
                      from flattrade.price_history
                      where instrument_token = any(%s) and "interval" = %s and close > 0) bars
                order by day, "time" desc
            """, (list(series), REFERENCE_INTERVAL))
            return {day: float(close) for day, close in cursor.fetchall()}

    def build(self, instrument_ids=None):
        """
        Detect, store and flag corrections for every instrument.

        Args:
            instrument_ids (set[str] | None): Restrict to these, or None for all.

        Returns:
            dict: Summary counts.
        """
        targets = self.instruments(instrument_ids)
        served = {}
        found = {}
        for position, (instrument_id, exchange, segment, symbol) in enumerate(targets, 1):
            served[instrument_id] = self.served(instrument_id)
            found[instrument_id] = []
            if position % 1000 == 0:
                LOGGER.info("corrections: read %d of %d instruments' served prices", position, len(targets))
        self.connection.rollback()

        # Pairs: the same symbol and segment family on both exchanges, both loaded.
        by_key = {}
        for instrument_id, exchange, segment, symbol in targets:
            by_key[(exchange, segment.split("_", 1)[1], symbol)] = instrument_id
        for (exchange, family, symbol), nse_id in by_key.items():
            if exchange != "nse":
                continue
            bse_id = by_key.get(("bse", family, symbol))
            if bse_id is None:
                continue
            self.count("pairs")
            for row in self.cross_exchange(nse_id, bse_id, served[nse_id], served[bse_id]):
                found[row["instrument_id"]].append(row)

        for position, (instrument_id, exchange, segment, symbol) in enumerate(targets, 1):
            closes = served[instrument_id]
            if closes:
                series = {entry[1] for entry in closes.values()}
                for row in self.intraday(instrument_id, closes, self.intraday_last_closes(series)):
                    self.merge(found[instrument_id], row)
                for row in self.yahoo_events(instrument_id, closes):
                    self.merge(found[instrument_id], row)
            self.store(instrument_id, found[instrument_id])
            if position % 1000 == 0:
                LOGGER.info("corrections: %d of %d, %s", position, len(targets), self.counts)
        return self.counts

    def split_events(self, instrument_ids):
        """
        The split events Yahoo lists for any of these instruments, whatever their status.

        Args:
            instrument_ids (list[str]): The instruments.

        Returns:
            list[tuple]: (event date, price factor) pairs, the price factor being 1 over Yahoo's ratio.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select distinct yahoo_event_date, yahoo_event_ratio from {tables.ADJUSTMENT_FACTORS}
                where instrument_id::text = any(%s) and yahoo_event_ratio is not null and yahoo_event_ratio > 0
            """, (instrument_ids,))
            return [(day, 1 / float(ratio)) for day, ratio in cursor.fetchall()]

    @staticmethod
    def own_level(closes, days, anchor, before):
        """
        The median of a series' own closes on the `PERSISTENCE` days nearest a date, on one side of it.

        Args:
            closes (dict): The series' served closes.
            days (list): The series' own dates, sorted.
            anchor (datetime.date): The date.
            before (bool): Take the days before `anchor` rather than from it.

        Returns:
            float | None: The median, or None without enough days.
        """
        if before:
            chosen = [day for day in days if day < anchor][-PERSISTENCE:]
        else:
            chosen = [day for day in days if day >= anchor][:PERSISTENCE]
        if len(chosen) < PERSISTENCE:
            return None
        return median(closes[day][0] for day in chosen)

    def cross_exchange(self, nse_id, bse_id, nse, bse):
        """
        Corrections found from the ratio of an instrument's BSE close to its NSE close.

        A step in the ratio says one series was served at a different scale before a date, but not
        which. Either series can be multiplied back into line, and each choice implies a different
        story for what both prices did on the day: correcting NSE leaves both moving as BSE did, and
        correcting BSE leaves both moving as NSE did. A choice whose common move is a rise of more than
        `IMPLAUSIBLE_RISE` is ruled out, since prices do not jump up several times over without a
        consolidation Yahoo would list. What remains is decided by a split Yahoo lists near the date,
        whose factor the right choice reproduces; failing that NSE is corrected, since flattrade's NSE
        series are the ones known to be served pre-adjusted, but the row stays provisional.

        Each side's move is measured between medians of its own closes just before and just after the
        transition, not between two shared days, so that a hole in one series - flattrade has no BSE
        bars from 2024-10-20 to 2024-11-20 - does not pass a month of trading off as a jump. When the
        transition falls in such a hole the ex-date is taken from Yahoo's event, and without one the row
        stays provisional.

        Args:
            nse_id (str): The NSE instrument.
            bse_id (str): The BSE instrument.
            nse (dict): The NSE served closes.
            bse (dict): The BSE served closes.

        Returns:
            list[dict]: Correction rows.
        """
        days = sorted(nse.keys() & bse.keys())
        if len(days) < PERSISTENCE * 2:
            return []
        ratios = [bse[day][0] / nse[day][0] for day in days]
        steps = level_steps(ratios, PAIR_TOLERANCE, anchor_tolerance=PAIR_ANCHOR_TOLERANCE)
        if steps is None:
            self.count("pairs_not_anchored")
            return []
        nse_days, bse_days = sorted(nse), sorted(bse)
        events = None
        rows = []
        for step in steps:
            index = step["index"]
            ratio = step["older"] / step["newer"]
            if max(ratio, 1 / ratio) < MINIMUM_PAIR_STEP:
                continue
            if events is None:
                events = self.split_events([nse_id, bse_id])
            # The last shared day at the older level, and the first at the newer one.
            last_older = index - 1
            while last_older > 0 and abs(ratios[last_older] / step["older"] - 1) > PAIR_TOLERANCE:
                last_older -= 1
            first_newer = index
            while first_newer < len(days) - 1 and abs(ratios[first_newer] / step["newer"] - 1) > PAIR_TOLERANCE:
                first_newer += 1
            before, after = days[last_older], days[first_newer]
            nse_change = _ratio(self.own_level(nse, nse_days, after, False), self.own_level(nse, nse_days, before + _DAY, True))
            bse_change = _ratio(self.own_level(bse, bse_days, after, False), self.own_level(bse, bse_days, before + _DAY, True))
            evidence = {"ratio_before": round(step["older"], 6), "ratio_after": round(step["newer"], 6),
                        "last_day_before": before, "first_day_after": after,
                        "nse_change": nse_change and round(nse_change, 4), "bse_change": bse_change and round(bse_change, 4),
                        "newer_run": step["newer_run"], "dispersion": round(step["dispersion"], 6)}
            if nse_change is None or bse_change is None:
                self.count("pair_steps_unattributed")
                continue

            # Correcting NSE multiplies its earlier prices by `ratio`, leaving both moving as BSE did;
            # correcting BSE multiplies its earlier prices by 1/ratio, leaving both moving as NSE did.
            options = {"nse": bse_change, "bse": nse_change}
            plausible = {side: move for side, move in options.items() if move <= IMPLAUSIBLE_RISE}
            event = next(((day, factor) for day, factor in sorted(events, key=lambda item: abs((item[0] - after).days))
                          if before - _DAY * MERGE_WINDOW_DAYS < day <= after + _DAY * MERGE_WINDOW_DAYS), None)
            if event is not None:
                evidence["yahoo_event"] = [event[0], round(event[1], 6)]
                # A listed event says something happened that day, which rules out the reading in which
                # neither price moved - even when the served scale does not equal the listed factor, as
                # with CGCL's NSE series, served at a quarter of its price for a bonus Yahoo lists as 1:1.
                acted = {side: move for side, move in plausible.items() if abs(_log(move)) >= 0.5 * abs(_log(ratio))}
                distances = sorted((abs(_log(move / event[1])), side) for side, move in plausible.items())
                # The two readings of a step differ by the step itself, so the margin cannot exceed it.
                margin = min(EVENT_MARGIN, 0.5 * abs(_log(ratio)))
                clear = len(distances) == 1 or distances[1][0] - distances[0][0] >= margin
                if len(acted) == 1:
                    side, backed = next(iter(acted)), True
                elif distances and distances[0][0] < EVENT_MATCH and clear:
                    side, backed = distances[0][1], True
                elif "nse" in plausible:
                    side, backed = "nse", False
                else:
                    side, backed = None, False
            elif len(plausible) == 1:
                side, backed = next(iter(plausible)), True
            elif "nse" in plausible:
                side, backed = "nse", False
            else:
                side, backed = None, False
            if side is None:
                self.count("pair_steps_unattributed")
                LOGGER.info("corrections: step on %s between %s and %s not attributable: nse x%.3f, bse x%.3f",
                            after, nse_id, bse_id, nse_change, bse_change)
                continue

            # The ex-date is where the served scale changed, which can be a day after Yahoo's: flattrade
            # divided NMDC's NSE bar of 2024-12-27, the ex-date of its 1:2 bonus, along with those before.
            ex_date = after
            in_hole = (after - before).days > MERGE_WINDOW_DAYS
            dated_by_event = event is not None and before < event[0] <= after
            if in_hole and dated_by_event:
                ex_date = event[0]
            adjusted_id, closes, multiplier = (nse_id, nse, ratio) if side == "nse" else (bse_id, bse, 1 / ratio)
            snapped = snap(multiplier)
            confirmed = (snapped is not None and backed and step["newer_run"] >= MINIMUM_NEWER_RUN
                         and not (in_hole and not dated_by_event))
            evidence["corrected"] = side
            if event is not None and backed and len(plausible) > 1:
                evidence["decided_by"] = "yahoo event"
            elif backed:
                evidence["decided_by"] = "only plausible reading"
            else:
                evidence["decided_by"] = "preference for correcting NSE"
            rows.extend(self.rows(adjusted_id, closes, ex_date, multiplier, snapped, "cross_exchange",
                                  "confirmed" if confirmed else "provisional", evidence))
        return rows

    def intraday(self, instrument_id, closes, last_bars):
        """
        Corrections found from the ratio of the day's last raw intraday bar to the daily close.

        Args:
            instrument_id (str): The instrument.
            closes (dict): Its served daily closes.
            last_bars (dict): The last intraday close of each day.

        Returns:
            list[dict]: Correction rows.
        """
        days = sorted(closes.keys() & last_bars.keys())
        if len(days) < PERSISTENCE * 2:
            return []
        ratios = [last_bars[day] / closes[day][0] for day in days]
        steps = level_steps(ratios, INTRADAY_TOLERANCE)
        if steps is None:
            return []
        rows = []
        for step in steps:
            multiplier = step["older"] / step["newer"]
            if max(multiplier, 1 / multiplier) < MINIMUM_INTRADAY_STEP:
                continue
            before, after = days[step["index"] - 1], days[step["index"]]
            snapped = snap(multiplier)
            confirmed = snapped is not None and step["newer_run"] >= MINIMUM_NEWER_RUN
            evidence = {"intraday_over_daily_before": round(step["older"], 6),
                        "intraday_over_daily_after": round(step["newer"], 6),
                        "daily_close_before": closes[before][0], "last_intraday_close_before": last_bars[before],
                        "newer_run": step["newer_run"], "dispersion": round(step["dispersion"], 6)}
            rows.extend(self.rows(instrument_id, closes, after, multiplier, snapped, "intraday",
                                  "confirmed" if confirmed else "provisional", evidence))
        return rows

    def yahoo_events(self, instrument_id, closes):
        """
        Provisional corrections for split events Yahoo lists where the served series shows no step.

        Args:
            instrument_id (str): The instrument.
            closes (dict): Its served daily closes.

        Returns:
            list[dict]: Provisional rows.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select ex_date, yahoo_event_ratio from {tables.ADJUSTMENT_FACTORS}
                where instrument_id = %s and source = 'yahoo_split_event' and status = 'rejected'
                  and yahoo_event_ratio is not null
            """, (instrument_id,))
            events = cursor.fetchall()
        days = sorted(closes)
        rows = []
        for ex_date, ratio in events:
            ratio = float(ratio)
            before = [day for day in days if day < ex_date]
            after = [day for day in days if day >= ex_date]
            if not before or not after:
                continue
            move = closes[after[0]][0] / closes[before[-1]][0]
            if abs(_log(move)) > 0.5 * abs(_log(ratio)):
                continue
            evidence = {"yahoo_ratio": ratio, "close_before": closes[before[-1]][0], "close_after": closes[after[0]][0],
                        "note": "Yahoo lists a split here and the served series does not move: pre-adjusted, "
                                "or a phantom event"}
            rows.extend(self.rows(instrument_id, closes, after[0], ratio, snap(ratio), "yahoo_event",
                                  "provisional", evidence))
        return rows

    @staticmethod
    def rows(instrument_id, closes, ex_date, multiplier, snapped, method, status, evidence):
        """
        One correction row for each of the instrument's series with bars before the ex-date.

        A correction belongs to the instrument's history, not to whichever token happened to trade on
        the day before: SUMEETINDS traded on its BE token across its 2025 split, and its EQ token's
        earlier bars were served at the same fifth of their price.

        Args:
            instrument_id (str): The instrument.
            closes (dict): Its served closes, each with the series it came from.
            ex_date (datetime.date): The first day served at the true scale.
            multiplier (float): The observed multiplier.
            snapped (Fraction | None): The simple ratio it snapped to.
            method (str): How it was found.
            status (str): "confirmed" or "provisional".
            evidence (dict): What was measured.

        Returns:
            list[dict]: The rows.
        """
        series = sorted({entry[1] for day, entry in closes.items() if day < ex_date})
        return [{"instrument_id": instrument_id, "broker_series": name, "ex_date": ex_date,
                 "price_multiplier": float(snapped) if snapped is not None else multiplier,
                 "snapped_ratio": f"{snapped.numerator}/{snapped.denominator}" if snapped is not None else None,
                 "observed": multiplier, "method": method, "status": status, "evidence": dict(evidence)}
                for name in series]

    @staticmethod
    def merge(rows, candidate):
        """
        Add a row unless one for the same series and nearby date exists, combining their evidence.

        A cross_exchange row is kept over an intraday one, and both over a yahoo_event one. Two
        methods that disagree on the multiplier by more than 2% leave the kept row provisional.

        Args:
            rows (list[dict]): The instrument's rows so far.
            candidate (dict): The new row.

        Returns:
            None: This function returns nothing.
        """
        rank = {"cross_exchange": 0, "intraday": 1, "yahoo_event": 2}
        for existing in rows:
            if existing["broker_series"] != candidate["broker_series"]:
                continue
            if abs((existing["ex_date"] - candidate["ex_date"]).days) > MERGE_WINDOW_DAYS:
                continue
            kept, other = (existing, candidate) if rank[existing["method"]] <= rank[candidate["method"]] \
                else (candidate, existing)
            kept["evidence"] = dict(kept["evidence"], **{f"{other['method']}_multiplier": round(other["observed"], 6)})
            if other["method"] == "yahoo_event":
                pass  # evidence only: a listed event proves nothing about the scale a series was served at
            elif abs(kept["price_multiplier"] / other["price_multiplier"] - 1) > 0.02:
                kept["status"] = "provisional"
            elif other["method"] != "yahoo_event" and other["status"] == "confirmed":
                kept["status"] = "confirmed" if kept["snapped_ratio"] else kept["status"]
            rows[rows.index(existing)] = kept
            return
        rows.append(candidate)

    def store(self, instrument_id, rows):
        """
        Replace an instrument's derived corrections, and flag it for rebuilding if the applied ones changed.

        Args:
            instrument_id (str): The instrument.
            rows (list[dict]): Its detected corrections.

        Returns:
            None: This function returns nothing.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select broker_series, ex_date, price_multiplier from {tables.PRICE_HISTORY_CORRECTIONS}
                where instrument_id = %s and "interval" = %s and status = 'confirmed'
            """, (instrument_id, INTERVAL))
            before = {(series, day, round(float(multiplier), 8)) for series, day, multiplier in cursor.fetchall()}

            cursor.execute(f"""
                delete from {tables.PRICE_HISTORY_CORRECTIONS}
                where instrument_id = %s and "interval" = %s and method <> 'manual' and status <> 'rejected'
                  and not (broker_series || '|' || ex_date::text = any(%s))
            """, (instrument_id, INTERVAL, [f"{row['broker_series']}|{row['ex_date'].isoformat()}" for row in rows]))
            for row in rows:
                cursor.execute(f"""
                    insert into {tables.PRICE_HISTORY_CORRECTIONS}
                        (broker, broker_series, "interval", ex_date, instrument_id, price_multiplier, method, status,
                         snapped_ratio, observed, evidence)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (broker, broker_series, "interval", ex_date) do update set
                        instrument_id = excluded.instrument_id, price_multiplier = excluded.price_multiplier,
                        method = excluded.method, status = excluded.status, snapped_ratio = excluded.snapped_ratio,
                        observed = excluded.observed, evidence = excluded.evidence, updated_at = now()
                    where {tables.PRICE_HISTORY_CORRECTIONS}.method <> 'manual'
                      and {tables.PRICE_HISTORY_CORRECTIONS}.status <> 'rejected'
                      and ({tables.PRICE_HISTORY_CORRECTIONS}.price_multiplier,
                           {tables.PRICE_HISTORY_CORRECTIONS}.status,
                           {tables.PRICE_HISTORY_CORRECTIONS}.evidence)
                          is distinct from (excluded.price_multiplier, excluded.status, excluded.evidence)
                """, (BROKER, row["broker_series"], INTERVAL, row["ex_date"], instrument_id,
                      round(row["price_multiplier"], 10), row["method"], row["status"], row["snapped_ratio"],
                      round(row["observed"], 10), json.dumps(row["evidence"], default=str)))
                self.count(f"{row['method']}_{row['status']}")

            cursor.execute(f"""
                select broker_series, ex_date, price_multiplier from {tables.PRICE_HISTORY_CORRECTIONS}
                where instrument_id = %s and "interval" = %s and status = 'confirmed'
            """, (instrument_id, INTERVAL))
            after = {(series, day, round(float(multiplier), 8)) for series, day, multiplier in cursor.fetchall()}

            if after != before:
                self.count("instruments_changed")
                cursor.execute(f"""
                    update {tables.PRICE_HISTORY_SOURCES} set broker_latest_seen = null
                    where instrument_id = %s and "interval" = %s
                """, (instrument_id, INTERVAL))
                cursor.execute(f"""
                    delete from {tables.ADJUSTMENT_FACTORS}
                    where instrument_id = %s and source = 'yahoo_split_event' and status = 'rejected'
                """, (instrument_id,))
                cursor.execute(f"""
                    update {tables.YAHOO_FETCH_STATE} set last_fetched_at = null where instrument_id = %s
                """, (instrument_id,))
        self.connection.commit()

_DAY = __import__("datetime").timedelta(days=1)

def _ratio(numerator, denominator):
    """A ratio, or None when either side is missing."""
    if numerator is None or not denominator:
        return None
    return numerator / denominator

def _log(value):
    """Natural logarithm, for comparing ratios symmetrically."""
    from math import log
    return log(value)
