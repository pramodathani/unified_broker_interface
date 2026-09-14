"""
Shared machinery for downloading a broker's historical candles into `<broker>.price_history`.

Each broker subclasses `BrokerCandles` and supplies four things: which intervals it serves and
what it calls them, how far back a single request may reach, how to fetch one window, and how to
read the response. Everything else - the rate limiter, the work queue, the watermarks, the
backoff, the upsert - is here, so a broker module is short.

## Why this is a queue rather than a loop

The job is enormous. Zerodha alone publishes over 110,000 instruments and serves eight intervals,
which is close to a million series, and the deepest of them reach back to 2005. At the three
requests a second Kite allows, a complete backfill is measured in weeks. So this is not a script
that runs to completion; it is a worker that makes progress whenever it is running and can be
stopped at any moment.

Two consequences shape everything below. Work is **claimed one window at a time** from a progress
table, so the process holds no state that a restart would lose. And the queue is **ordered by
priority**, so that the data most likely to be wanted - cash daily bars - lands on the first
night, while the long tail of expired option minute bars drains for as long as it is allowed to.

## Nothing is derived

A five minute bar is whatever the broker returned for five minutes. It is not six one minute bars
added together. That costs roughly three times the requests, and it means the stored data can be
compared against the broker's own charts without an argument about aggregation boundaries.
"""

import time
import datetime
import zoneinfo
from collections import namedtuple

from psycopg2.extras import execute_values

from utilities.configurations import get_postgres, get_logger

# Every exchange in this project trades in India, and every broker here stamps its bars against
# that clock whatever offset it puts on the wire.
INDIA_TIMEZONE = zoneinfo.ZoneInfo("Asia/Kolkata")

# What the unified price layer needs to know about one of a broker's series in order to find its
# instrument. `broker_token` is compared against `match_on` in unified.broker_mappings -
# `broker_token` for most brokers, `order_symbol` where the price table names the instrument by its
# ticker. `exchange` is the canonical exchange, or None when the identifier does not say.
# `segments` are the canonical segments the series can belong to, or None for any.
# `exchange_token` is the exchange's own number for the instrument where the identifier yields one,
# which lets other brokers' mappings of that number vouch for a series its own broker never mapped.
# `symbol` is the exchange trading symbol, without any series suffix, where the identifier has it.
SeriesContext = namedtuple("SeriesContext",
                           ["broker_token", "exchange", "segments", "match_on", "exchange_token", "symbol"],
                           defaults=(None, None, "broker_token", None, None))

# A series that fails this many times in a row stops being claimed until a human looks at it.
MAXIMUM_CONSECUTIVE_FAILURES = 5

# Consecutive empty windows before concluding the broker has no more history for a series. One
# empty window is normal - a holiday fortnight, a contract that had not listed yet.
MAXIMUM_EMPTY_WINDOWS = 3

# Rows per COPY-style insert. Large enough to amortise the round trip, small enough that one
# window's failure does not roll back an hour of work.
WRITE_BATCH_ROWS = 5000

class CandleError(Exception):
    """Base for the failures a candle download distinguishes between."""

class CandleThrottled(CandleError):
    """The broker asked us to slow down. Back off and retry the same window."""

class CandleAuthenticationError(CandleError):
    """The session is not usable. Nothing else will work either, so stop this broker."""

class CandleBlocked(CandleError):
    """
    The broker is refusing this client outright, not pacing it. Stop this broker.

    The difference from `CandleThrottled` is what retrying does. A throttle clears once the pace
    drops, so backing off and moving on to the next series is right. A block - a firewall ban on
    the IP address, such as Cloudflare's error 1015 in front of Fyers - is extended by every
    further request, and moving on to the next series is simply another request. It is also not a
    session problem, so logging in again would only be one more refused request. The one useful
    response is to stop and let the process manager bring the download back later.
    """

class CandleInstrumentUnknown(CandleError):
    """
    The broker will not serve this series at all.

    Usually an expired contract: Kite answers `invalid token` for an instrument that has left its
    dump, and no amount of retrying changes that. The series is retired rather than retried.
    """

def is_intraday(interval):
    """
    Whether a stored interval name divides the session rather than spanning whole days.

    Several brokers split their candle API in two, one endpoint for intraday bars and another for
    daily and coarser ones, so the module has to know which side of that split a name falls on.
    Stored interval names are this project's own, and every intraday one ends in `minute`.

    - `interval` is the stored interval name, such as `5minute` or `day`.
    """
    return str(interval).endswith("minute")

def daily_bar_time(moment):
    """
    Put a daily or coarser bar at midnight India time on the trading date it belongs to.

    Brokers disagree, silently, about what a daily bar's timestamp means. Measured on the same
    RELIANCE session: Kite stamps midnight India time, Fyers stamps midnight UTC, and Dhan sends
    an epoch that decodes to 18:30 UTC - which is the same midnight India time Kite means. Stored
    as received, the same trading day would sit at three different instants depending on which
    broker answered, and comparing one broker's day bar against another's would be an argument
    about time zones rather than about prices.

    Every one of those conventions names the same date once read in India time, since no broker
    stamps a bar before the day it belongs to. So the trading date is recovered by converting to
    India time, and midnight India time is the value they all converge on.

    Intraday bars are left alone: their timestamps are already unambiguous, and moving them would
    be changing the data.

    - `moment` is a timezone aware timestamp as the broker reported it.
    """
    if moment.tzinfo is None:
        raise ValueError(f"A bar time must be timezone aware to be normalised, got {moment!r}.")
    india_moment = moment.astimezone(INDIA_TIMEZONE)
    return datetime.datetime(india_moment.year, india_moment.month, india_moment.day,
                             tzinfo=INDIA_TIMEZONE)

class RateLimiter:
    """
    Holds a caller to a request rate, and to a daily budget where the broker sets one.

    Deliberately a sleeping limiter with no queue and no threads. One process per broker makes
    the requests in sequence, which is the simplest thing that respects a published limit, and
    the limits here are low enough that concurrency would buy little before hitting them.
    """

    def __init__(self, requests_per_second, requests_per_day=None):
        """
        Rate limiter for one broker.

        - `requests_per_second` is the sustained rate to hold.
        - `requests_per_day` is the broker's daily cap, or None when it publishes none.
        """
        self._minimum_gap = 1.0 / float(requests_per_second)
        self._next_slot = 0.0
        self._requests_per_day = requests_per_day
        self._spent_today = 0
        self._budget_date = datetime.date.today()

    def take(self):
        """
        Wait until the next request may be made, and account for it.

        Raises `CandleThrottled` when the daily budget is exhausted, which the caller treats as a
        reason to stop for the day rather than to retry.
        """
        today = datetime.date.today()
        if today != self._budget_date:
            self._budget_date = today
            self._spent_today = 0

        if self._requests_per_day is not None and self._spent_today >= self._requests_per_day:
            raise CandleThrottled(
                f"Daily budget of {self._requests_per_day} requests is spent.")

        now = time.monotonic()
        if now < self._next_slot:
            time.sleep(self._next_slot - now)
        self._next_slot = max(now, self._next_slot) + self._minimum_gap
        self._spent_today += 1

    def back_off(self, seconds):
        """
        Push the next request further out, after the broker said no.

        - `seconds` is how long to wait beyond the normal gap.
        """
        self._next_slot = max(self._next_slot, time.monotonic()) + seconds

class BrokerCandles:
    """
    Base class for one broker's historical candle download.

    A subclass sets the class attributes below and implements `fetch_candles` and
    `parse_response`.

    - `BROKER_NAME` is the broker, which is also its PostgreSQL schema.
    - `INTERVALS` maps the name stored in the table to the name the broker's API expects.
    - `MAXIMUM_WINDOW_DAYS` is how many days one request may span, per interval.
    - `REQUESTS_PER_SECOND` and `REQUESTS_PER_DAY` are the broker's published limits.
    - `EARLIEST_AVAILABLE_DATE` is as far back as the broker serves anything.
    - `TOKEN_COLUMN`, `TYPE_COLUMN` and `EXPIRY_COLUMN` name the columns in this broker's
      instrument master that hold the identifier the API wants, the instrument type, and the
      expiry - the last two only to decide priority.
    """

    BROKER_NAME = ""
    INTERVALS = {}
    MAXIMUM_WINDOW_DAYS = {}
    REQUESTS_PER_SECOND = 1.0
    REQUESTS_PER_DAY = None
    EARLIEST_AVAILABLE_DATE = datetime.date(2010, 1, 1)

    TOKEN_COLUMN = "instrument_token"
    TYPE_COLUMN = "instrument_type"
    EXPIRY_COLUMN = "expiry"

    @classmethod
    def series_context(cls, identifier):
        """
        Say what instrument one of this broker's stored series can belong to, without logging in.

        A classmethod on purpose: constructing a downloader establishes a broker session, and the
        unified price layer reads series for every broker without wanting a session for any. The
        default treats the identifier as the broker's own token with nothing known about exchange
        or segment; a broker whose identifier carries more says so by overriding this.

        Args:
            identifier (str): The `instrument_token` value in this broker's price table.

        Returns:
            SeriesContext: The token to look up, and the exchange and segments to look within.
        """
        return SeriesContext(str(identifier))

    def __init__(self):
        """
        Candle downloader for one broker.
        """
        self._connection = get_postgres()
        self._logger = get_logger(f"candles.{self.BROKER_NAME}")
        self._limiter = RateLimiter(self.REQUESTS_PER_SECOND, self.REQUESTS_PER_DAY)
        self._table = f"{self.BROKER_NAME}.price_history"
        self._progress_table = f"{self.BROKER_NAME}.price_history_progress"
        # Whether the one login allowed after a refused session has been spent. See `_fetch_bars`.
        self._relogin_used = False

    # ---- what the subclass provides -------------------------------------------------------

    def fetch_candles(self, token, interval, start_date, end_date):
        """
        Fetch one window of candles from the broker.

        Returns whatever the broker's response decodes to; `parse_response` turns it into bars.
        Raises one of the `CandleError` subclasses to say how the caller should react.

        The interval arrives as this project's stored name rather than as the broker's code, and
        the module translates it with `self.INTERVALS[interval]` where it needs the code. Several
        brokers need both: the name says whether to call the daily endpoint or the intraday one,
        and the code is what goes in the request.

        - `token` is the broker's own instrument identifier, as `instruments` produced it.
        - `interval` is the stored interval name, a key of `INTERVALS`.
        - `start_date` and `end_date` bound the window, inclusive.
        """
        raise NotImplementedError

    def parse_response(self, payload, interval):
        """
        Turn a broker response into a list of `(time, open, high, low, close, volume, oi)` tuples.

        `time` must be a timezone aware `datetime`, not the broker's text. The watermarks come
        back from Postgres as datetimes and are compared against these, so a parser that passes
        strings through fails the moment a series starts collecting forward. A daily or coarser
        bar goes through `daily_bar_time`, because brokers disagree about what its timestamp
        means.

        - `payload` is whatever `fetch_candles` returned.
        - `interval` is the stored interval name the window was asked for. Brokers whose bar
          times depend on the interval - a platform that stamps the end of a bar rather than its
          start, or one that needs a daily bar normalised - need it; the rest ignore it.
        """
        raise NotImplementedError

    # ---- the instrument universe ------------------------------------------------------------

    def instruments(self):
        """
        Every instrument this broker has ever published, with the fields priority needs.

        The most recent snapshot each token appeared in, not merely today's: a contract that
        expired last month is still worth asking about, and the answer decides whether it is
        retired. Today's snapshot alone would silently narrow the universe to whatever is live.
        """
        query = f"""
            select distinct on (i."{self.TOKEN_COLUMN}")
                   i."{self.TOKEN_COLUMN}", i."{self.TYPE_COLUMN}", i."{self.EXPIRY_COLUMN}"
            from {self.BROKER_NAME}.instruments i
            where i."{self.TOKEN_COLUMN}" is not null and i."{self.TOKEN_COLUMN}" <> ''
            order by i."{self.TOKEN_COLUMN}", i.download_date desc
        """
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchall()

    def priority_for(self, instrument_type, expiry, interval):
        """
        Where a series sits in the queue. Lower is worked first.

        The ordering is the difference between useful data in days and useful data in months.
        Cash instruments come first because they have the deepest history and are wanted most;
        expired options come last because there are tens of thousands of them, each holding a few
        weeks of data, and most will be refused outright. Coarse intervals beat fine ones within
        each tier, since a day bar covers a year in one request and a minute bar covers two
        months.

        - `instrument_type` is the broker's own type string.
        - `expiry` is the contract expiry, or None for cash.
        - `interval` is the stored interval name.
        """
        kind = (instrument_type or "").upper()
        expired = False
        if expiry:
            try:
                expired = datetime.date.fromisoformat(str(expiry)[:10]) < datetime.date.today()
            except ValueError:
                expired = False

        if not expiry:
            base = 10                                   # cash: equities, indices
        elif kind in ("FUT", "FUTSTK", "FUTIDX", "FUTCOM", "FUTCUR"):
            base = 80 if expired else 30
        else:
            base = 90 if expired else 60                # options, live or dead

        if interval in ("day", "week", "month"):
            return base
        minutes = self._interval_minutes(interval)
        return base + (5 if minutes >= 15 else 15)

    @staticmethod
    def _interval_minutes(interval):
        """
        Minutes in an interval name like `15minute`, or 0 when it is not a minute interval.

        - `interval` is the stored interval name.
        """
        if not interval.endswith("minute"):
            return 0
        try:
            return int(interval[:-len("minute")])
        except ValueError:
            return 0

    def seed(self):
        """
        Make sure every instrument and interval this broker serves has a progress row.

        Safe to run again: existing rows are left exactly as they are, so re-seeding after a new
        instrument master picks up what is new without disturbing what is already downloaded.
        Returns how many rows were added.
        """
        instruments = self.instruments()
        if not instruments:
            self._logger.warning(f"No instruments for {self.BROKER_NAME}; nothing to seed. "
                                 f"Has the instrument master been downloaded?")
            return 0

        today = datetime.date.today()
        considered = 0
        batch = []

        with self._connection.cursor() as cursor:
            # Counted by measuring the table, not by summing cursor.rowcount: execute_values
            # splits a batch into pages of its own, and rowcount then reports only the last page,
            # which made a complete seed of 1,149,064 rows announce itself as 22,964.
            cursor.execute(f"select count(*) from {self._progress_table}")
            before = cursor.fetchone()[0]

            # Written a batch at a time as the instruments are walked rather than assembled in
            # full first. Wisdom Capital alone is 372,545 instruments across thirteen intervals,
            # and holding all 4.8 million rows in memory to write them costs a gigabyte for
            # nothing.
            for token, instrument_type, expiry in instruments:
                for interval in self.INTERVALS:
                    batch.append((str(token), interval,
                                  self.priority_for(instrument_type, expiry, interval), today))
                considered += len(self.INTERVALS)
                if len(batch) >= WRITE_BATCH_ROWS:
                    self._insert_series(cursor, batch)
                    batch = []
            if batch:
                self._insert_series(cursor, batch)

            cursor.execute(f"select count(*) from {self._progress_table}")
            added = cursor.fetchone()[0] - before
        self._connection.commit()
        self._logger.info(f"Seeded {added} new series ({considered} considered).")
        return added

    def _insert_series(self, cursor, batch):
        """
        Register one batch of series, leaving any that already exist exactly as they are.

        - `cursor` is an open cursor on this broker's connection.
        - `batch` is a list of `(token, interval, priority, seeded_date)` tuples.
        """
        execute_values(cursor, f"""
            insert into {self._progress_table}
                (instrument_token, "interval", priority, seeded_date)
            values %s
            on conflict (instrument_token, "interval") do nothing
        """, batch, page_size=WRITE_BATCH_ROWS)

    # ---- the work queue ---------------------------------------------------------------------

    def claim(self):
        """
        The next series due for a window, or None when there is nothing to do.

        Ordered by priority and then by how long a series has been waiting. Series that have
        reached the broker's limit, or that are backing off after failures, are skipped.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                select instrument_token, "interval", earliest_bar_time, latest_bar_time,
                       oldest_requested_time, empty_window_streak, consecutive_failures
                from {self._progress_table}
                where reached_broker_limit = false
                  and consecutive_failures < %s
                  and (next_attempt_after is null or next_attempt_after <= now())
                order by priority, last_attempt_at nulls first
                limit 1
            """, (MAXIMUM_CONSECUTIVE_FAILURES,))
            row = cursor.fetchone()
        self._connection.commit()
        return row

    def next_window(self, series):
        """
        The date range to ask for next, as a `(start, end, direction)` triple.

        The backward walk comes first and runs to completion. A series starts at today and steps
        back a window at a time until it reaches the broker's earliest date or the broker stops
        returning anything, and only then does it start filling forward with whatever has
        happened since.

        Doing it the other way round - preferring forward whenever the last stored bar is older
        than today - looks reasonable and does not work: outside market hours the last bar is
        always older than today, so the series asks for the same empty recent window forever and
        never walks back at all.

        - `series` is a row from `claim`.
        """
        _, interval, earliest, latest, oldest_requested, _, _ = series
        span = datetime.timedelta(days=self.MAXIMUM_WINDOW_DAYS.get(interval, 60) - 1)
        today = datetime.date.today()

        backward_done = (oldest_requested is not None
                         and oldest_requested.date() <= self.EARLIEST_AVAILABLE_DATE)

        if not backward_done:
            end = today if oldest_requested is None else (oldest_requested.date()
                                                          - datetime.timedelta(days=1))
            start = max(end - span, self.EARLIEST_AVAILABLE_DATE)
            if start > end:
                return None, None, "exhausted"
            return start, end, "backward"

        if latest is None:
            return None, None, "exhausted"
        start = latest.date()
        if start >= today:
            return None, None, "current"
        return start, min(start + span, today), "forward"

    # ---- one unit of work --------------------------------------------------------------------

    # ---- a refused session ------------------------------------------------------------------

    def _fetch_bars(self, token, interval, start_date, end_date):
        """
        Fetch and parse one window, logging in once first if the broker refuses the session.

        A token expiring does not mean the download is over, and it does not mean this series is at
        fault. The rule is to log in first and then carry on: one login, then the same window
        again. Only if that login fails, or the fresh session is refused as well, does the error go
        back up - where `visit` and `run` stop the broker rather than carry on with a dead token.

        Both alternatives are worse. Stopping outright leaves the download waiting for systemd to
        restart it into a login, and recording the refusal against whichever series it was on and
        moving to the next sends thousands of refused requests an hour - enough for Cloudflare to
        ban the machine from Fyers.

        The login is re-armed by any window that comes back without a session error, so a
        backfill that runs for weeks gets its one login at each daily expiry.

        - `token`, `interval`, `start_date` and `end_date` are as for `fetch_candles`.
        """
        try:
            bars = self.parse_response(self.fetch_candles(token, interval, start_date, end_date),
                                       interval)
        except CandleAuthenticationError as failure:
            if self._relogin_used:
                raise
            self._relogin_used = True
            self._logger.warning(f"{self.BROKER_NAME} refused the session ({failure}). Logging in "
                                 f"once before continuing.")
            self.relogin()
            self._limiter.take()
            bars = self.parse_response(self.fetch_candles(token, interval, start_date, end_date),
                                       interval)
        self._relogin_used = False
        return bars

    def relogin(self):
        """
        Establish a fresh session and rebuild everything built on the old one.

        Through `ensure_session`, so it takes the same Redis lock and obeys the same floor on login
        attempts as any other process using it - which means it may wait, and may find another
        process has already logged in, in which case that session is simply used.

        Raises:
            CandleAuthenticationError: If no working session could be established.
        """
        from stock_brokers.api.session import ensure_session

        try:
            ensure_session(self.BROKER_NAME, logger=self._logger)
            self._api = self._build_api()
            self.after_relogin()
        except CandleAuthenticationError:
            raise
        except Exception as exception:
            raise CandleAuthenticationError(
                f"logging in again did not produce a working session: "
                f"{type(exception).__name__}: {str(exception)[:200]}") from exception
        self._logger.info(f"{self.BROKER_NAME} logged in again. Continuing.")

    def _build_api(self):
        """
        Construct this broker's authenticated API class, around whatever session is now stored.

        The broker's own class from `api_class_for`, which is what every downloader builds. A
        downloader that builds its API differently overrides this.
        """
        from stock_brokers.api.session import api_class_for

        return api_class_for(self.BROKER_NAME)()

    def after_relogin(self):
        """
        Re-establish anything a downloader keeps on top of the broker session. Nothing by default.

        For a broker whose historical endpoint takes a second credential minted from the session,
        such as a separate market data token, this is where that credential is renewed.
        """

    def visit(self, series):
        """
        Fetch one window for one series and store it, advancing the watermark.

        Returns the number of bars stored. The bars and the watermark are written in the same
        transaction, so an interruption costs at most the window in flight - and repeating that
        window is harmless, because bars upsert on their key.

        - `series` is a row from `claim`.
        """
        token, interval, _, previous_latest, _, empty_streak, _ = series
        start_date, end_date, direction = self.next_window(series)

        if direction == "exhausted":
            if previous_latest is None:
                # Walked the whole range the broker serves and never saw a bar. A contract that
                # listed and never traded is the usual case, and there are tens of thousands of
                # them. Without this they would be claimed again the moment they were put down -
                # `next_window` answers "exhausted" every time, so nothing would move - and the
                # queue would spin through them at database speed making no requests at all.
                self._retire(token, interval,
                             "the broker served no bars anywhere in the range it offers")
                return 0
            # The backward walk is finished. Not retired: the series still gets new bars each
            # day, it simply has no more past to collect.
            self._finish_backfill(token, interval, "reached the broker's earliest date")
            return 0
        if direction == "current":
            self._defer_until_tomorrow(token, interval, "up to date")
            return 0

        self._limiter.take()
        try:
            bars = self._fetch_bars(token, interval, start_date, end_date)
        except CandleInstrumentUnknown as exception:
            self._retire(token, interval, str(exception))
            return 0
        except CandleThrottled as exception:
            # A throttle says something about the pace, not about this series, so it costs the
            # limiter five seconds and leaves the series claimable. Counting it as a failure
            # instead would push a perfectly good series an hour into the future - and a broker
            # that throttles does it to a run of series, not to one.
            self._limiter.back_off(5.0)
            self._record_throttle(token, interval, str(exception))
            return 0
        except (CandleAuthenticationError, CandleBlocked):
            # Neither says anything about this series, so neither is recorded against it. Before a
            # dead token was re-raised here, every refused request landed on whichever series was
            # claimed, and after five of those a good series stopped being claimed at all.
            raise
        except Exception as exception:
            self._record_failure(token, interval,
                                 f"{type(exception).__name__}: {str(exception)[:200]}")
            return 0

        if not bars:
            streak = (empty_streak or 0) + 1
            if direction == "backward" and streak >= MAXIMUM_EMPTY_WINDOWS:
                # The broker has nothing older. Stop walking back, keep collecting forward.
                self._finish_backfill(token, interval,
                                      f"{streak} empty windows walking back from {end_date}")
            elif direction == "forward":
                self._defer_until_tomorrow(token, interval, "no new bars yet")
            else:
                self._record_empty(token, interval, streak, start_date, direction)
            return 0

        self._store(token, interval, bars, start_date, direction, previous_latest)
        return len(bars)

    def _store(self, token, interval, bars, requested_from, direction, previous_latest=None):
        """
        Write a window's bars and move the watermark, in one transaction.

        - `token` is the broker's instrument identifier.
        - `interval` is the stored interval name.
        - `bars` are the parsed `(time, open, high, low, close, volume, oi)` tuples.
        - `requested_from` is the start of the window that was asked for.
        - `direction` is whether the walk was forward or backward.
        - `previous_latest` is the newest bar already stored, used to tell a forward window that
          gained ground from one that returned only what was already known.
        """
        # Collapsed on bar time before the write, last one winning. A broker can answer with the
        # same timestamp twice in one window - Dhan does - and Postgres refuses a batch that
        # touches the same row twice with "ON CONFLICT DO UPDATE command cannot affect row a
        # second time", which killed the whole process rather than the window.
        by_time = {}
        for bar in bars:
            by_time[bar[0]] = (bar[0], str(token), interval,
                               bar[1], bar[2], bar[3], bar[4], bar[5], bar[6])
        rows = list(by_time.values())
        times = list(by_time)

        try:
            with self._connection.cursor() as cursor:
                for start in range(0, len(rows), WRITE_BATCH_ROWS):
                    execute_values(cursor, f"""
                        insert into {self._table}
                            ("time", instrument_token, "interval", open, high, low, close,
                             volume, oi)
                        values %s
                        on conflict (instrument_token, "interval", "time") do update set
                            open = excluded.open, high = excluded.high, low = excluded.low,
                            close = excluded.close, volume = excluded.volume, oi = excluded.oi,
                            downloaded_at = now()
                    """, rows[start:start + WRITE_BATCH_ROWS])

                cursor.execute(f"""
                    update {self._progress_table} set
                        earliest_bar_time = least(coalesce(earliest_bar_time, %s), %s),
                        latest_bar_time = greatest(coalesce(latest_bar_time, %s), %s),
                        oldest_requested_time = case when %s = 'backward'
                            then least(coalesce(oldest_requested_time, %s), %s)
                            else oldest_requested_time end,
                        bar_count = bar_count + %s,
                        empty_window_streak = 0,
                        consecutive_failures = 0,
                        next_attempt_after = null,
                        last_attempt_at = now(),
                        last_outcome = 'stored',
                        last_failure_reason = null
                    where instrument_token = %s and "interval" = %s
                """, (min(times), min(times), max(times), max(times),
                      direction, requested_from, requested_from,
                      len(rows), str(token), interval))
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

        # A forward window that returned nothing newer than what was already stored means the
        # market has not produced more yet. Without this the series would be claimed again
        # immediately and spend the rate limit re-fetching the same bars all weekend.
        if direction == "forward" and previous_latest is not None and max(times) <= previous_latest:
            self._defer_until_tomorrow(token, interval, "forward window gained no new bars")

    def _record_empty(self, token, interval, streak, requested_from, direction):
        """
        Note that a window came back with nothing, and step past it.

        - `token`, `interval` identify the series.
        - `streak` is how many empty windows in a row this makes.
        - `requested_from` is the start of the window that was asked for.
        - `direction` is whether the walk was forward or backward.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                update {self._progress_table} set
                    empty_window_streak = %s,
                    oldest_requested_time = case when %s = 'backward'
                        then least(coalesce(oldest_requested_time, %s), %s)
                        else oldest_requested_time end,
                    last_attempt_at = now(),
                    last_outcome = 'empty',
                    consecutive_failures = 0,
                    next_attempt_after = null
                where instrument_token = %s and "interval" = %s
            """, (streak, direction, requested_from, requested_from, str(token), interval))
        self._connection.commit()

    def _finish_backfill(self, token, interval, reason):
        """
        Mark the backward walk complete, leaving the series collecting forward.

        Distinct from `_retire`: the broker has no more *past* for this series, but it will keep
        producing new bars. Retiring it here would quietly stop a live instrument updating.

        - `token`, `interval` identify the series.
        - `reason` is why the walk stopped, kept for review.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                update {self._progress_table} set
                    oldest_requested_time = %s,
                    empty_window_streak = 0,
                    consecutive_failures = 0,
                    next_attempt_after = null,
                    last_attempt_at = now(),
                    last_outcome = 'backfilled',
                    limit_reason = %s
                where instrument_token = %s and "interval" = %s
            """, (self.EARLIEST_AVAILABLE_DATE, reason[:500], str(token), interval))
        self._connection.commit()
        self._logger.info(f"{token} {interval}: backfill complete ({reason}).")

    def _defer_until_tomorrow(self, token, interval, reason):
        """
        Put a series aside until the next day.

        Reached when a forward window brings nothing new, which outside market hours is every
        forward window. Without it the highest priority series would be re-fetched continuously
        and spend the whole rate limit re-reading bars already stored.

        - `token`, `interval` identify the series.
        - `reason` is recorded as the outcome.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                update {self._progress_table} set
                    next_attempt_after = date_trunc('day', now()) + interval '1 day',
                    last_attempt_at = now(),
                    last_outcome = %s,
                    consecutive_failures = 0
                where instrument_token = %s and "interval" = %s
            """, (reason[:100], str(token), interval))
        self._connection.commit()

    def _record_throttle(self, token, interval, reason):
        """
        Note that the broker asked us to slow down, without holding it against the series.

        The window is left exactly as it was, so the same series is claimed again once the
        limiter's back off has passed and the work is simply redone.

        - `token`, `interval` identify the series.
        - `reason` is what the broker said.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                update {self._progress_table} set
                    last_attempt_at = now(),
                    last_outcome = 'throttled',
                    last_failure_reason = %s
                where instrument_token = %s and "interval" = %s
            """, (reason[:500], str(token), interval))
        self._connection.commit()
        self._logger.warning(f"{token} {interval}: throttled: {reason[:150]}")

    def _record_failure(self, token, interval, reason):
        """
        Note a failure and push the next attempt out exponentially.

        An hour, then two, four, eight and so on, so a series that is permanently broken stops
        crowding out the ones that are not.

        - `token`, `interval` identify the series.
        - `reason` is what went wrong, stored for a human to read.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                update {self._progress_table} set
                    consecutive_failures = consecutive_failures + 1,
                    next_attempt_after = now() + interval '1 hour'
                                         * power(2, least(consecutive_failures, 6)),
                    last_attempt_at = now(),
                    last_outcome = 'failed',
                    last_failure_reason = %s
                where instrument_token = %s and "interval" = %s
            """, (reason[:500], str(token), interval))
        self._connection.commit()
        self._logger.warning(f"{token} {interval}: {reason}")

    def _retire(self, token, interval, reason):
        """
        Stop asking for a series the broker will not serve.

        - `token`, `interval` identify the series.
        - `reason` is why, stored so the decision can be reviewed.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                update {self._progress_table} set
                    reached_broker_limit = true,
                    limit_reason = %s,
                    last_attempt_at = now(),
                    last_outcome = 'retired'
                where instrument_token = %s and "interval" = %s
            """, (reason[:500], str(token), interval))
        self._connection.commit()

    # ---- the loop ------------------------------------------------------------------------------

    def run(self, stop_event=None, deadline_seconds=None):
        """
        Work the queue until stopped, out of work, or out of time.

        Returns a `(visits, bars)` pair.

        - `stop_event` is a `threading.Event` that ends the loop when set.
        - `deadline_seconds` ends the loop after this long, for a job with a nightly window.
        """
        started = time.monotonic()
        visits = 0
        bars = 0

        while True:
            if stop_event is not None and stop_event.is_set():
                self._logger.info("Stopping: asked to.")
                break
            if deadline_seconds is not None and time.monotonic() - started > deadline_seconds:
                self._logger.info(f"Stopping: reached the {deadline_seconds}s deadline.")
                break

            series = self.claim()
            if series is None:
                self._logger.info("Nothing due. The queue is drained or backing off.")
                break

            try:
                stored = self.visit(series)
            except (CandleAuthenticationError, CandleBlocked) as exception:
                self._logger.error(f"Stopping: {type(exception).__name__}: {exception}")
                break
            except CandleThrottled as exception:
                self._logger.warning(f"Stopping: {exception}")
                break
            except Exception as exception:
                # Anything `visit` did not expect - a response shaped in a way no probe produced,
                # a write the database refuses - costs this one series and not the run. Before
                # this, a single window that failed on the way into Postgres took the process
                # down, and since the same window would be claimed again on restart it took it
                # down every ten minutes thereafter.
                self._connection.rollback()
                self._record_failure(series[0], series[1],
                                     f"{type(exception).__name__}: {str(exception)[:200]}")
                self._logger.exception(f"{series[0]} {series[1]}: unexpected failure, "
                                       f"carrying on with the next series.")
                stored = 0

            visits += 1
            bars += stored
            if visits % 200 == 0:
                self._logger.info(f"{visits} windows, {bars} bars so far.")

        self._logger.info(f"Finished: {visits} windows, {bars} bars.")
        return visits, bars

    def summary(self):
        """
        How far the download has got, for a status display.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(f"""
                select count(*),
                       count(*) filter (where reached_broker_limit),
                       count(*) filter (where bar_count > 0),
                       coalesce(sum(bar_count), 0),
                       count(*) filter (where consecutive_failures >= %s)
                from {self._progress_table}
            """, (MAXIMUM_CONSECUTIVE_FAILURES,))
            total, retired, started, stored, stuck = cursor.fetchone()
        self._connection.commit()
        return {"series": total, "retired": retired, "with_bars": started,
                "bars": int(stored), "stuck": stuck}

    def close(self):
        """
        Close the database connection.
        """
        self._connection.close()
