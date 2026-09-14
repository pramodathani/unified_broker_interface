"""
Copy the brokers' stored bars into unified.price_history.

One run, for one interval, goes:

1. **Discover.** Every series with bars in each source broker's `price_history_progress`.
2. **Resolve.** Each series to its instrument, through `resolution`, and each (series, instrument)
   to a row in unified.price_history_sources, kept when the source policy allows that broker
   for that instrument's segment. A row whose series now resolves elsewhere is marked superseded.
3. **Choose work.** An instrument is rebuilt when one of its sources is new, superseded, or has
   bars its source row has not seen: the broker's earliest bar moved earlier, or its latest later.
4. **Stitch.** For each instrument, the primary broker's series are laid over each other by time.
   Where two have the same bar, the series with the most recent bars wins, since that is the token
   the instrument trades under now. INDIAGLYCO's EQ series owns its days up to 2026-09-01 and its BE
   series from 2026-09-02; ORICONENT's BE series fills the six weeks of 2026 when EQ had no bars.
5. **Gap-fill.** A gap-fill broker supplies only the trading days the primary has no bar for, and
   only when its bars agree with the primary's on the days both have.
6. **Filter.** Bars on days the exchange did not trade, off the interval's grid, or with a high
   below the open or close or a low above them, are dropped and counted.
7. **Write.** Upserted, with a row only rewritten when a value actually differs so that a re-run
   does not decompress chunks for nothing; bars no source provides any more are deleted; and the
   source rows' watermarks moved - all in one transaction per instrument.

An instrument is rebuilt over its whole history for daily bars, which is at most a few thousand
rows. Nothing is ever averaged between brokers.
"""

import datetime
from collections import Counter, namedtuple
from decimal import ROUND_HALF_UP, Decimal

from psycopg2.extras import execute_values

from stock_brokers.instruments.historical.utilities.unified.calendar import TradingCalendar, on_grid
from stock_brokers.instruments.historical.utilities.unified.resolution import SeriesResolver
from stock_brokers.instruments.historical.utilities.unified.sources import (GAP_FILL_AGREEMENT,
                                                                            brokers_for_interval,
                                                                            price_basis, sources_for)
from utilities.configurations import get_logger, get_postgres
from stock_brokers.instruments.historical.utilities.unified import tables

LOGGER = get_logger("unified_prices")

WRITE_BATCH_ROWS = 5000

# A gap-fill broker's close agrees with the primary's within this share of the price.
AGREEMENT_TOLERANCE = Decimal("0.0005")

# And it needs at least this many shared bars before its agreement means anything.
MINIMUM_OVERLAP = 20

Bar = namedtuple("Bar", ["time", "open", "high", "low", "close", "volume", "oi"])

# A source row as the loader works with it.
Source = namedtuple("Source", [
    "source_id", "broker", "broker_series", "instrument_id", "role", "exchange", "valid_from", "valid_to",
    "broker_earliest", "broker_latest", "changed",
])

PAISA = Decimal("0.01")

def corrected_bar(bar, price_multiplier, volume_multiplier):
    """
    A bar with a correction applied.

    Args:
        bar (Bar): The bar as served.
        price_multiplier (Decimal): What the prices were divided by.
        volume_multiplier (Decimal): What the volume was divided by.

    Returns:
        Bar: The corrected bar.
    """
    def price(value):
        # Half away from zero, as PostgreSQL's round() does, so the check in `verify` agrees to the paisa.
        return None if value is None else (value * price_multiplier).quantize(PAISA, rounding=ROUND_HALF_UP)
    volume = bar.volume if bar.volume is None or volume_multiplier == 1 else int(round(bar.volume * volume_multiplier))
    return bar._replace(open=price(bar.open), high=price(bar.high), low=price(bar.low), close=price(bar.close),
                        volume=volume)

class UnifiedLoader:
    """
    Loads one interval of bars into unified.price_history.

    Attributes:
        interval (str): The stored interval name being loaded.
        connection: The psycopg2 connection everything is read and written through.
        resolver (SeriesResolver): Finds each series' instrument.
        calendar (TradingCalendar): Trading days per exchange.
        counts (Counter): What the run did, for its summary.
    """

    def __init__(self, interval, instrument_ids=None, resolver=None, calendar=None):
        """
        Prepare a load.

        Args:
            interval (str): The stored interval name, for example "day".
            instrument_ids (set[str] | None): Restrict the load to these instruments, or None for all.
            resolver (SeriesResolver | None): A resolver to share, or None to build one.
            calendar (TradingCalendar | None): A calendar to share, or None to build one.

        Returns:
            None: This function returns nothing.
        """
        self.interval = interval
        self.instrument_ids = set(instrument_ids) if instrument_ids else None
        self.connection = get_postgres()
        self.resolver = resolver or SeriesResolver()
        self.calendar = calendar or TradingCalendar()
        self.counts = Counter()
        self.unresolved = []

    def run(self):
        """
        Discover, resolve and load.

        Returns:
            Counter: What was done - series seen, instruments rebuilt, bars written, deleted and filtered.
        """
        sources = self.refresh_sources()
        by_instrument = {}
        for source in sources:
            by_instrument.setdefault(source.instrument_id, []).append(source)

        work = [instrument_id for instrument_id, members in by_instrument.items()
                if any(source.changed for source in members)]
        LOGGER.info("%s: %d instruments with sources, %d to rebuild",
                    self.interval, len(by_instrument), len(work))
        for position, instrument_id in enumerate(sorted(work), 1):
            self.rebuild(instrument_id, by_instrument[instrument_id])
            if position % 500 == 0:
                LOGGER.info("%s: rebuilt %d of %d instruments", self.interval, position, len(work))
        self.counts["instruments_rebuilt"] += len(work)
        return self.counts

    def refresh_sources(self):
        """
        Resolve every series of every source broker and bring the sources table up to date.

        Returns:
            list[Source]: The active sources, restricted to `instrument_ids` when given.
        """
        existing = {}
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select source_id, broker, broker_series, instrument_id::text, status,
                       broker_earliest_seen, broker_latest_seen, owned_from, owned_to
                from {tables.PRICE_HISTORY_SOURCES} where "interval" = %s
            """, (self.interval,))
            for row in cursor.fetchall():
                existing[(row[1], row[2], row[3])] = row

        sources = []
        superseded = set()
        seen_keys = set()
        for broker in brokers_for_interval(self.interval):
            with self.connection.cursor() as cursor:
                cursor.execute(f"""
                    select instrument_token, earliest_bar_time, latest_bar_time
                    from {broker}.price_history_progress
                    where "interval" = %s and bar_count > 0 and earliest_bar_time is not null
                """, (self.interval,))
                progress = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
            self.counts[f"series_{broker}"] = len(progress)

            resolutions = self.resolver.resolve(broker, list(progress))
            for identifier, found in resolutions.items():
                earliest, latest = progress[identifier]
                for resolution in found:
                    if resolution.instrument_id is None:
                        self.counts[f"unresolved_{broker}"] += 1
                        self.unresolved.append((broker, identifier, resolution.status, resolution.status_reason))
                        continue
                    role = dict(sources_for(resolution.exchange, resolution.segment, self.interval)).get(broker)
                    if role is None:
                        continue
                    key = (broker, identifier, resolution.instrument_id)
                    seen_keys.add(key)
                    if self.instrument_ids is not None and resolution.instrument_id not in self.instrument_ids:
                        continue
                    previous = existing.get(key)
                    changed = (previous is None or previous[4] != "active"
                               or previous[5] is None or earliest < previous[5]
                               or previous[6] is None or latest > previous[6])
                    source_id = self.upsert_source(broker, identifier, resolution, role)
                    sources.append(Source(source_id, broker, identifier, resolution.instrument_id, role,
                                          resolution.exchange, resolution.valid_from, resolution.valid_to,
                                          earliest, latest, changed))

        # A series that no longer resolves to an instrument it used to feed.
        for key, row in existing.items():
            if key in seen_keys or row[4] != "active":
                continue
            if self.instrument_ids is not None and key[2] not in self.instrument_ids:
                continue
            with self.connection.cursor() as cursor:
                cursor.execute(f"""
                    update {tables.PRICE_HISTORY_SOURCES}
                    set status = 'superseded', status_reason = 'series no longer resolves to this instrument'
                    where source_id = %s
                """, (row[0],))
            superseded.add(key[2])
        self.connection.commit()
        self.counts["sources_superseded"] += len(superseded)

        # An instrument that lost a source is rebuilt from what it has left.
        if superseded:
            instruments_with_sources = {source.instrument_id for source in sources}
            for instrument_id in superseded:
                if instrument_id in instruments_with_sources:
                    sources = [source._replace(changed=True) if source.instrument_id == instrument_id else source
                               for source in sources]
                else:
                    sources.append(Source(None, None, None, instrument_id, None, None, None, None,
                                          None, None, True))
        return sources

    def upsert_source(self, broker, identifier, resolution, role):
        """
        Insert or refresh one source row, returning its id.

        Args:
            broker (str): The broker.
            identifier (str): The broker's series identifier.
            resolution (Resolution): The instrument it resolved to.
            role (str): "primary" or "gap_fill".

        Returns:
            int: The source_id.
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                insert into {tables.PRICE_HISTORY_SOURCES}
                    (broker, broker_series, "interval", instrument_id, resolved_by, mapping_first_date,
                     mapping_last_date, price_basis, role, status, status_reason)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
                on conflict (broker, broker_series, "interval", instrument_id) do update set
                    resolved_by = excluded.resolved_by,
                    mapping_first_date = excluded.mapping_first_date,
                    mapping_last_date = excluded.mapping_last_date,
                    price_basis = excluded.price_basis,
                    role = excluded.role,
                    status = case when {tables.PRICE_HISTORY_SOURCES}.resolved_by = 'manual'
                                  then {tables.PRICE_HISTORY_SOURCES}.status else 'active' end,
                    status_reason = excluded.status_reason
                returning source_id
            """, (broker, identifier, self.interval, resolution.instrument_id, resolution.resolved_by,
                  resolution.mapping_first_date, resolution.mapping_last_date,
                  price_basis(resolution.segment), role, resolution.status_reason))
            return cursor.fetchone()[0]

    def read_series(self, source):
        """
        One source's bars, restricted to the part of the series that belongs to its instrument, with
        any confirmed correction from unified.price_history_corrections applied.

        A corrected price is rounded to the paisa: the broker rounded when it divided, so multiplying
        back restores the raw price to within that rounding and no closer.

        Args:
            source (Source): The source.

        Returns:
            list[Bar]: The bars, oldest first.
        """
        conditions = ['instrument_token = %s', '"interval" = %s']
        parameters = [source.broker_series, self.interval]
        if source.valid_from is not None:
            conditions.append('"time" >= %s')
            parameters.append(source.valid_from)
        if source.valid_to is not None:
            conditions.append('"time" < %s')
            parameters.append(source.valid_to)
        with self.connection.cursor() as cursor:
            cursor.execute(f"""
                select "time", open, high, low, close, volume, oi from {source.broker}.price_history
                where {' and '.join(conditions)} order by "time"
            """, parameters)
            bars = [Bar(*row) for row in cursor.fetchall()]
            cursor.execute(f"""
                select valid_from, valid_to, price_multiplier, volume_multiplier from {tables.CORRECTION_RANGES}
                where broker = %s and broker_series = %s and "interval" = %s
            """, (source.broker, source.broker_series, self.interval))
            ranges = cursor.fetchall()
        if not ranges:
            return bars
        corrected = []
        for bar in bars:
            for valid_from, valid_to, price_multiplier, volume_multiplier in ranges:
                if valid_from <= bar.time < valid_to:
                    bar = corrected_bar(bar, price_multiplier, volume_multiplier)
                    self.counts["bars_corrected"] += 1
                    break
            corrected.append(bar)
        return corrected

    def stitch(self, members):
        """
        Lay one broker's series for an instrument over each other, the most recent series on top.

        Args:
            members (list[Source]): The instrument's sources at one broker.

        Returns:
            dict: Bar time to (Bar, source_id).
        """
        ordered = sorted(members, key=lambda source: source.broker_latest)
        bars = {}
        for source in ordered:
            for bar in self.read_series(source):
                bars[bar.time] = (bar, source.source_id)
        return bars

    def valid(self, bar, exchange):
        """
        Whether a bar passes the calendar, grid and range checks, counting why when it does not.

        Args:
            bar (Bar): The bar.
            exchange (str): The instrument's exchange.

        Returns:
            bool: True if the bar is kept.
        """
        if None in (bar.open, bar.high, bar.low, bar.close) or min(bar.open, bar.high, bar.low, bar.close) <= 0:
            self.counts["filtered_missing_price"] += 1
            return False
        if exchange in ("nse", "bse"):
            day = bar.time.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).date()
            if not self.calendar.is_trading_day(exchange, day):
                self.counts["filtered_non_trading_day"] += 1
                return False
        if not on_grid(bar.time, self.interval):
            self.counts["filtered_off_grid"] += 1
            return False
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            self.counts["filtered_bad_range"] += 1
            return False
        return True

    @staticmethod
    def agreement(primary, other):
        """
        The share of shared bar times on which two brokers' closes agree.

        Args:
            primary (dict): Bar time to (Bar, source_id).
            other (dict): Bar time to (Bar, source_id).

        Returns:
            tuple[float, int]: The share agreeing, and how many bars were compared.
        """
        shared = primary.keys() & other.keys()
        if not shared:
            return 0.0, 0
        agreeing = 0
        for moment in shared:
            first = primary[moment][0].close
            second = other[moment][0].close
            if first is not None and second is not None and abs(first - second) <= AGREEMENT_TOLERANCE * abs(first):
                agreeing += 1
        return agreeing / len(shared), len(shared)

    def rebuild(self, instrument_id, members):
        """
        Rebuild one instrument's bars from its sources, in one transaction.

        Args:
            instrument_id (str): The instrument.
            members (list[Source]): Its sources; a list holding only a placeholder with no broker
                means every source is gone and its bars are deleted.

        Returns:
            None: This function returns nothing.
        """
        real = [source for source in members if source.broker is not None]
        chosen = {}
        contributed = Counter()
        if real:
            exchange = real[0].exchange
            primaries = [source for source in real if source.role == "primary"]
            by_broker = {}
            for source in primaries:
                by_broker.setdefault(source.broker, []).append(source)
            # One primary broker per instrument; the policy never names two.
            for broker, broker_sources in by_broker.items():
                for moment, (bar, source_id) in self.stitch(broker_sources).items():
                    chosen[moment] = (bar, source_id)

            fillers = {}
            for source in real:
                if source.role == "gap_fill":
                    fillers.setdefault(source.broker, []).append(source)
            for broker, broker_sources in fillers.items():
                offered = self.stitch(broker_sources)
                share, compared = self.agreement(chosen, offered)
                if chosen and (compared < MINIMUM_OVERLAP or share < GAP_FILL_AGREEMENT):
                    self.counts["gap_fill_refused"] += 1
                    LOGGER.info("%s %s: %s refused as gap-fill, %.4f agreement over %d bars",
                                self.interval, instrument_id, broker, share, compared)
                    continue
                for moment, entry in offered.items():
                    if moment not in chosen:
                        chosen[moment] = entry
                        self.counts["bars_gap_filled"] += 1

            kept = {}
            for moment, (bar, source_id) in chosen.items():
                if self.valid(bar, exchange):
                    kept[moment] = (bar, source_id)
            chosen = kept

        rows = []
        for moment, (bar, source_id) in sorted(chosen.items()):
            rows.append((moment, instrument_id, self.interval, bar.open, bar.high, bar.low, bar.close,
                         bar.volume, bar.oi, source_id))
            contributed[source_id] += 1

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"""
                    select "time" from {tables.PRICE_HISTORY}
                    where instrument_id = %s and "interval" = %s
                """, (instrument_id, self.interval))
                stale = [row[0] for row in cursor.fetchall() if row[0] not in chosen]
                for start in range(0, len(stale), WRITE_BATCH_ROWS):
                    cursor.execute(f"""
                        delete from {tables.PRICE_HISTORY}
                        where instrument_id = %s and "interval" = %s and "time" = any(%s)
                    """, (instrument_id, self.interval, stale[start:start + WRITE_BATCH_ROWS]))
                self.counts["bars_deleted"] += len(stale)

                for start in range(0, len(rows), WRITE_BATCH_ROWS):
                    execute_values(cursor, f"""
                        insert into {tables.PRICE_HISTORY}
                            ("time", instrument_id, "interval", open, high, low, close, volume, oi, source_id)
                        values %s
                        on conflict (instrument_id, "interval", "time") do update set
                            open = excluded.open, high = excluded.high, low = excluded.low,
                            close = excluded.close, volume = excluded.volume, oi = excluded.oi,
                            source_id = excluded.source_id, loaded_at = now()
                        where ({tables.PRICE_HISTORY}.open, {tables.PRICE_HISTORY}.high,
                               {tables.PRICE_HISTORY}.low, {tables.PRICE_HISTORY}.close,
                               {tables.PRICE_HISTORY}.volume, {tables.PRICE_HISTORY}.oi,
                               {tables.PRICE_HISTORY}.source_id)
                            is distinct from
                              (excluded.open, excluded.high, excluded.low, excluded.close,
                               excluded.volume, excluded.oi, excluded.source_id)
                    """, rows[start:start + WRITE_BATCH_ROWS], page_size=WRITE_BATCH_ROWS)
                    self.counts["bars_written"] += cursor.rowcount

                for source in real:
                    times = [moment for moment, (_, source_id) in chosen.items() if source_id == source.source_id]
                    cursor.execute(f"""
                        update {tables.PRICE_HISTORY_SOURCES} set
                            broker_earliest_seen = %s,
                            broker_latest_seen = %s,
                            owned_from = %s,
                            owned_to = %s,
                            loaded_earliest = %s,
                            loaded_latest = %s,
                            last_loaded_at = now()
                        where source_id = %s
                    """, (source.broker_earliest, source.broker_latest,
                          min(times) if times else None, max(times) if times else None,
                          min(times) if times else None, max(times) if times else None,
                          source.source_id))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        self.counts["bars_kept"] += len(rows)

# Intraday bars are built by each broker from its own tick stream, so two brokers' bars for the same
# quarter hour differ slightly even when neither is wrong: across a sample of BSE 15 minute bars,
# flattrade and wisdom_capital closes agree within 0.05% on 88-97% of bars, and within 1% on 97-100%,
# the illiquid GOODRICKE being the lowest. What the check has to catch is an adjusted or broken
# series, which misses by a whole factor, so the intraday test is looser than the daily one.
INTRADAY_AGREEMENT_TOLERANCE = Decimal("0.01")
INTRADAY_GAP_FILL_AGREEMENT = 0.95

# How far before a source's last seen bar an incremental intraday rebuild starts, so that a window
# the downloader re-fetched and corrected is picked up.
INTRADAY_OVERLAP = datetime.timedelta(days=3)

class IntradayLoader(UnifiedLoader):
    """
    Loads intraday bars, set-based in SQL.

    Intraday history is two orders of magnitude larger than daily - flattrade alone stores some 300
    million intraday bars - so bars are never brought into Python. Each instrument is rebuilt only
    from the point its sources changed: from three days before the newest bar its source rows had
    seen, or from the beginning for a new source or one whose history grew backwards.

    The rebuild for one instrument deletes its bars in that window and inserts the stitched ones in
    a single statement, `DISTINCT ON` the bar time with the most recent series first; then inserts a
    gap-fill broker's bars for whole trading days the primary does not have, when the gap-fill broker
    agrees with the primary on the days both have. Trading days come from a temporary table filled
    once from the calendar; the grid and range checks are expressions in the same statement.
    """

    def __init__(self, interval, instrument_ids=None, resolver=None, calendar=None):
        """
        Prepare an intraday load.

        Args:
            interval (str): The stored intraday interval name, for example "15minute".
            instrument_ids (set[str] | None): Restrict the load to these instruments, or None for all.
            resolver (SeriesResolver | None): A resolver to share, or None to build one.
            calendar (TradingCalendar | None): A calendar to share, or None to build one.

        Returns:
            None: This function returns nothing.
        """
        super().__init__(interval, instrument_ids, resolver, calendar)
        from stock_brokers.instruments.historical.utilities.unified.sources import INTRADAY_MINUTES
        self.minutes = INTRADAY_MINUTES[interval]
        with self.connection.cursor() as cursor:
            cursor.execute("create temporary table if not exists unified_trading_days (exchange text, day date, "
                           "primary key (exchange, day))")
            cursor.execute("truncate unified_trading_days")
            for exchange in ("nse", "bse"):
                execute_values(cursor, "insert into unified_trading_days values %s",
                               [(exchange, day) for day in self.calendar.trading_days(exchange)], page_size=10000)
            cursor.execute(f"""
                select source_id, broker_earliest_seen, broker_latest_seen
                from {tables.PRICE_HISTORY_SOURCES} where "interval" = %s
            """, (interval,))
            self.previously_seen = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        self.connection.commit()

    def window_start(self, members):
        """
        Where an instrument's rebuild starts.

        The whole history is rebuilt when a source is new, when a source lost, or when one's history
        grew backwards; otherwise from a little before the newest bar any changed source had seen.

        Args:
            members (list[Source]): The instrument's sources.

        Returns:
            datetime.datetime: The first bar time to rebuild.
        """
        beginning = datetime.datetime(1990, 1, 1, tzinfo=datetime.timezone.utc)
        starts = []
        for source in members:
            if source.broker is None:
                return beginning
            previous_earliest, previous_latest = self.previously_seen.get(source.source_id, (None, None))
            if previous_earliest is None or previous_latest is None:
                return beginning
            if source.broker_earliest < previous_earliest:
                return beginning
            if source.changed:
                starts.append(previous_latest - INTRADAY_OVERLAP)
        return min(starts) if starts else beginning

    def rebuild(self, instrument_id, members):
        """
        Rebuild one instrument's intraday bars from where its sources changed, in one transaction.

        Args:
            instrument_id (str): The instrument.
            members (list[Source]): Its sources.

        Returns:
            None: This function returns nothing.
        """
        real = [source for source in members if source.broker is not None]
        start = self.window_start(members)

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"""
                    delete from {tables.PRICE_HISTORY}
                    where instrument_id = %s and "interval" = %s and "time" >= %s
                """, (instrument_id, self.interval, start))
                self.counts["bars_deleted"] += cursor.rowcount

                exchange = real[0].exchange if real else None
                primaries = [source for source in real if source.role == "primary"]
                fillers = [source for source in real if source.role == "gap_fill"]
                if primaries:
                    self.insert_bars(cursor, instrument_id, exchange, primaries, start, whole_days_only=False)
                by_broker = {}
                for source in fillers:
                    by_broker.setdefault(source.broker, []).append(source)
                for broker, broker_sources in by_broker.items():
                    share, compared = self.intraday_agreement(cursor, instrument_id, broker_sources)
                    if primaries and (compared < MINIMUM_OVERLAP or share < INTRADAY_GAP_FILL_AGREEMENT):
                        self.counts["gap_fill_refused"] += 1
                        LOGGER.info("%s %s: %s refused as gap-fill, %.4f agreement over %d bars",
                                    self.interval, instrument_id, broker, share, compared)
                        continue
                    self.insert_bars(cursor, instrument_id, exchange, broker_sources, start, whole_days_only=True)

                for source in real:
                    cursor.execute(f"""
                        update {tables.PRICE_HISTORY_SOURCES} s set
                            broker_earliest_seen = %s, broker_latest_seen = %s,
                            owned_from = b.first_bar, owned_to = b.last_bar,
                            loaded_earliest = b.first_bar, loaded_latest = b.last_bar, last_loaded_at = now()
                        from (select min("time") as first_bar, max("time") as last_bar
                              from {tables.PRICE_HISTORY}
                              where instrument_id = %s and "interval" = %s and source_id = %s) b
                        where s.source_id = %s
                    """, (source.broker_earliest, source.broker_latest, instrument_id, self.interval,
                          source.source_id, source.source_id))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def insert_bars(self, cursor, instrument_id, exchange, sources, start, whole_days_only):
        """
        Insert one broker's stitched bars for an instrument from `start`.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor inside the instrument's transaction.
            instrument_id (str): The instrument.
            exchange (str): Its exchange, for the trading day check.
            sources (list[Source]): The broker's series for the instrument.
            start (datetime.datetime): The first bar time to insert.
            whole_days_only (bool): Insert only on India dates the instrument has no bar for yet.

        Returns:
            None: This function returns nothing.
        """
        broker = sources[0].broker
        ranked = sorted(sources, key=lambda source: source.broker_latest, reverse=True)
        series_values = [(source.broker_series, source.source_id, rank, source.valid_from, source.valid_to)
                         for rank, source in enumerate(ranked)]
        day = "((b.\"time\" at time zone 'Asia/Kolkata')::date)"
        since_open = ("(extract(hour from b.\"time\" at time zone 'Asia/Kolkata') * 60 "
                      "+ extract(minute from b.\"time\" at time zone 'Asia/Kolkata') - 555)")
        missing_day = ""
        if whole_days_only:
            missing_day = f"""
                and not exists (select 1 from {tables.PRICE_HISTORY} u
                                where u.instrument_id = %(instrument_id)s and u."interval" = %(interval)s
                                  and u."time" >= {day}::timestamp at time zone 'Asia/Kolkata'
                                  and u."time" < ({day} + 1)::timestamp at time zone 'Asia/Kolkata')"""
        trading_day = ""
        if exchange in ("nse", "bse"):
            trading_day = f"and exists (select 1 from unified_trading_days t where t.exchange = %(exchange)s and t.day = {day})"
        statement = f"""
            insert into {tables.PRICE_HISTORY}
                ("time", instrument_id, "interval", open, high, low, close, volume, oi, source_id)
            select distinct on (b."time")
                b."time", %(instrument_id)s, b."interval", b.open, b.high, b.low, b.close, b.volume, b.oi, s.source_id
            from {broker}.price_history b
            join (values %(series)s) as s(series, source_id, rank, valid_from, valid_to)
              on b.instrument_token = s.series
            where b."interval" = %(interval)s and b."time" >= %(start)s
              and (s.valid_from is null or b."time" >= s.valid_from::timestamptz)
              and (s.valid_to is null or b."time" < s.valid_to::timestamptz)
              and b.open > 0 and b.high > 0 and b.low > 0 and b.close > 0
              and b.high >= greatest(b.open, b.close) and b.low <= least(b.open, b.close)
              and extract(second from b."time") = 0
              and {since_open} >= 0 and {since_open}::int %% %(minutes)s = 0
              {trading_day}
              {missing_day}
            order by b."time", s.rank
            on conflict (instrument_id, "interval", "time") do nothing
        """
        from psycopg2.extensions import AsIs
        rendered_series = ",".join(cursor.mogrify("(%s, %s, %s, %s::text, %s::text)", values).decode()
                                   for values in series_values)
        cursor.execute(statement, {"instrument_id": instrument_id, "interval": self.interval, "start": start,
                                   "exchange": exchange, "minutes": self.minutes, "series": AsIs(rendered_series)})
        self.counts["bars_gap_filled" if whole_days_only else "bars_written"] += cursor.rowcount

    def intraday_agreement(self, cursor, instrument_id, sources):
        """
        The share of bars on which a gap-fill broker's close agrees with the bars already inserted.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.
            instrument_id (str): The instrument.
            sources (list[Source]): The gap-fill broker's series.

        Returns:
            tuple[float, int]: The share agreeing, and how many bars were compared.
        """
        broker = sources[0].broker
        cursor.execute(f"""
            select count(*), count(*) filter (where abs(b.close - u.close) <= %s * abs(u.close))
            from {tables.PRICE_HISTORY} u
            join {broker}.price_history b
              on b.instrument_token = any(%s) and b."interval" = u."interval" and b."time" = u."time"
            where u.instrument_id = %s and u."interval" = %s
        """, (INTRADAY_AGREEMENT_TOLERANCE, [source.broker_series for source in sources], instrument_id, self.interval))
        compared, agreeing = cursor.fetchone()
        return (agreeing / compared if compared else 0.0), compared
