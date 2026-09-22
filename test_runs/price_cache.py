"""Offline checks of the Redis copy of candles that `/api/instruments/prices` serves.

`unified_broker_interface/utilities/price_cache.py` is run against a stand-in Redis that keeps its keys in a dictionary, so no Redis, database, credentials or network are used. The checks cover slicing a stored copy, widening the range read from the database, the intraday span the widening must not exceed, and every reason a stored copy is thrown away.

Typical usage:

    python -m test_runs.price_cache
"""

import json
import sys
from datetime import date, datetime, time, timedelta

from unified_broker_interface.utilities.instrument_identity import INDIA
from unified_broker_interface.utilities.price_cache import (
    MAXIMUM_ENTRY_BYTES,
    PriceCache,
)

DAILY_COLUMNS = [
    'time',
    'open',
    'high',
    'low',
    'close',
    'volume',
    'oi',
]

ADJUSTED_COLUMNS = DAILY_COLUMNS + ['price_factor']


class StandInPipeline:
    """A Redis pipeline that reads the stand-in's dictionary.

    Attributes:
        cache (StandInCache): The cache the pipeline reads.
        keys (list): The keys queued so far.
    """

    def __init__(self, cache):
        """Builds the pipeline.

        Args:
            cache (StandInCache): The cache the pipeline reads.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.keys = []

    def get(self, key):
        """Queues a read.

        Args:
            key (str): The key to read.

        Returns:
            None: This method returns nothing.
        """
        self.keys.append(key)

    def execute(self):
        """Runs the queued reads.

        Returns:
            list: One value per queued key, None where the key is unset.

        Raises:
            RuntimeError: When the cache has been told to fail.
        """
        if self.cache.fails:
            raise RuntimeError('Redis is unreachable')
        return [self.cache.values.get(key) for key in self.keys]


class StandInCache:
    """A Redis client that keeps its keys in a dictionary.

    Attributes:
        values (dict): The keys and their string values.
        expiries (dict): The keys and the expiry each was set with.
        fails (bool): Whether every command raises instead of answering.
        writes (int): How many times a key has been set.
    """

    def __init__(self, values=None):
        """Builds the cache.

        Args:
            values (dict | None): The keys to start with, or None for none.

        Returns:
            None: This method returns nothing.
        """
        self.values = dict(values or {})
        self.expiries = {}
        self.fails = False
        self.writes = 0

    def pipeline(self):
        """A pipeline over this cache.

        Returns:
            StandInPipeline: The pipeline.

        Raises:
            RuntimeError: When the cache has been told to fail.
        """
        if self.fails:
            raise RuntimeError('Redis is unreachable')
        return StandInPipeline(self)

    def set(self, key, value, ex=None):
        """Stores a key.

        Args:
            key (str): The key to store.
            value (str): The value to store.
            ex (int | None): The expiry in seconds, or None for none.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the cache has been told to fail.
        """
        if self.fails:
            raise RuntimeError('Redis is unreachable')
        self.values[key] = value
        self.expiries[key] = ex
        self.writes += 1


class PriceCacheSuite:
    """Runs every check of the candle cache and reports how many passed.

    Attributes:
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.passed = 0
        self.failed = []

    def check(self, name, found, expected):
        """Records whether one check gave the expected value.

        Args:
            name (str): The check's name.
            found (object): What the code gave.
            expected (object): What it should have given.

        Returns:
            None: This method returns nothing.
        """
        if found == expected:
            self.passed += 1
            return
        self.failed.append(name)
        print(f'FAILED {name}')
        print(f'  expected {expected!r}')
        print(f'  found    {found!r}')

    def last_run(self, finished):
        """A price history run as `unified:prices:last_run` holds it.

        Args:
            finished (str): When the run finished.

        Returns:
            str: The run's outcome as JSON.
        """
        return json.dumps({
            'step': 'load',
            'started': finished,
            'finished': finished,
            'exit_code': 0,
        })

    def candles(self, first_day, count, factor=None):
        """Daily candles on consecutive days, in the shape the endpoint sends them.

        Args:
            first_day (datetime.date): The first day to make a candle for.
            count (int): How many candles to make.
            factor (float | None): A price factor to append, or None to leave the candles unadjusted.

        Returns:
            list: The candles, oldest first.
        """
        series = []
        for offset in range(count):
            day = first_day + timedelta(days=offset)
            candle = [
                f'{day.isoformat()}T00:00:00+05:30',
                100.0 + offset,
                101.0 + offset,
                99.0 + offset,
                100.5 + offset,
                1000 + offset,
                None,
            ]
            if factor is not None:
                candle.append(factor)
            series.append(candle)
        return series

    def cache_with_run(self, finished='2026-09-22 08:31:04'):
        """A stand-in cache holding one recorded price history run.

        Args:
            finished (str): When the recorded run finished.

        Returns:
            StandInCache: The cache.
        """
        return StandInCache({'unified:prices:last_run': self.last_run(finished)})

    def series_cache(self, cache, columns=None, known_as_of=None, basis='unadjusted'):
        """A `PriceCache` for one series, with its copy already read.

        Args:
            cache (StandInCache): The cache to read.
            columns (list | None): The answer's columns, or None for the daily ones.
            known_as_of (datetime.date | None): The adjustment cut-off, or None for every factor.
            basis (str): The price basis.

        Returns:
            PriceCache: The loaded cache.
        """
        stored = PriceCache(cache, 'a2c4e6f8-0000-4000-8000-000000000001', 'day', basis, known_as_of,
                            columns or DAILY_COLUMNS)
        stored.load()
        return stored

    def india_midnight(self, day):
        """The instant an India calendar day begins, as the endpoint bounds a range with.

        Args:
            day (datetime.date): The day.

        Returns:
            datetime.datetime: Midnight India time on that day.
        """
        return datetime.combine(day, time.min, tzinfo=INDIA)

    def sliced(self, stored, from_date, to_date):
        """The stored candles for a range of India calendar days, both inclusive.

        Args:
            stored (PriceCache): The loaded cache.
            from_date (datetime.date): The first day to include.
            to_date (datetime.date): The last day to include.

        Returns:
            list: The days the sliced candles are stamped with.
        """
        series = stored.between(self.india_midnight(from_date),
                                self.india_midnight(to_date + timedelta(days=1)))
        return [candle[0][:10] for candle in series]

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.cold_cache_reads_the_range_asked_for()
        self.a_stored_copy_answers_the_same_range()
        self.a_stored_copy_answers_a_sub_range()
        self.a_range_outside_the_copy_widens_the_read()
        self.widening_stops_at_the_intraday_span()
        self.a_later_loader_run_discards_the_copy()
        self.other_columns_discard_the_copy()
        self.an_unrecorded_run_still_caches()
        self.an_unreadable_run_turns_the_cache_off()
        self.an_oversized_answer_is_not_stored()
        self.an_unreachable_redis_is_not_an_error()
        self.each_basis_and_cut_off_has_its_own_key()

        total = self.passed + len(self.failed)
        print(f'{self.passed}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def cold_cache_reads_the_range_asked_for(self):
        """An empty cache covers nothing and asks the database for exactly the range requested.

        Returns:
            None: This method returns nothing.
        """
        stored = self.series_cache(self.cache_with_run())
        self.check('an empty cache covers nothing', stored.covers(date(2026, 1, 1), date(2026, 1, 31)), False)
        self.check('an empty cache reads the range asked for',
                   stored.query_range(date(2026, 1, 1), date(2026, 1, 31), None),
                   (date(2026, 1, 1), date(2026, 1, 31)))

    def a_stored_copy_answers_the_same_range(self):
        """A copy written by one request answers the next identical request without a read.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        first = self.series_cache(cache)
        first.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10))
        self.check('a copy is written', cache.writes, 1)
        self.check('a copy is written with the backstop expiry', cache.expiries[first.key], 86400)
        self.check('the writing request is not served from the cache', first.loaded, False)

        second = self.series_cache(cache)
        self.check('the copy is read back', second.loaded, True)
        self.check('the copy covers the range it was written for',
                   second.covers(date(2026, 1, 1), date(2026, 1, 10)), True)
        self.check('the copy answers the whole range',
                   self.sliced(second, date(2026, 1, 1), date(2026, 1, 10)),
                   [f'2026-01-{day:02d}' for day in range(1, 11)])
        self.check('reading the copy writes nothing', cache.writes, 1)

    def a_stored_copy_answers_a_sub_range(self):
        """A range inside the copy is sliced out of it, with both bounds included.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        first = self.series_cache(cache)
        first.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10))

        stored = self.series_cache(cache)
        self.check('a sub-range is covered', stored.covers(date(2026, 1, 3), date(2026, 1, 5)), True)
        self.check('a sub-range includes both of its bounds',
                   self.sliced(stored, date(2026, 1, 3), date(2026, 1, 5)),
                   ['2026-01-03', '2026-01-04', '2026-01-05'])
        self.check('one day is one candle',
                   self.sliced(stored, date(2026, 1, 7), date(2026, 1, 7)), ['2026-01-07'])
        self.check('the first day of the copy is covered',
                   self.sliced(stored, date(2026, 1, 1), date(2026, 1, 1)), ['2026-01-01'])
        self.check('the last day of the copy is covered',
                   self.sliced(stored, date(2026, 1, 10), date(2026, 1, 10)), ['2026-01-10'])
        self.check('a range before the copy is empty',
                   self.sliced(stored, date(2025, 12, 1), date(2025, 12, 31)), [])
        self.check('a range after the copy is empty',
                   self.sliced(stored, date(2026, 2, 1), date(2026, 2, 28)), [])
        self.check('a day the market was shut is empty',
                   self.sliced(stored, date(2026, 1, 11), date(2026, 1, 11)), [])

    def a_range_outside_the_copy_widens_the_read(self):
        """A request reaching past the copy reads the union of the two ranges, and replaces the copy.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        first = self.series_cache(cache)
        first.replace(date(2026, 1, 10), date(2026, 1, 20), self.candles(date(2026, 1, 10), 11))

        stored = self.series_cache(cache)
        self.check('a range reaching back is not covered',
                   stored.covers(date(2026, 1, 1), date(2026, 1, 15)), False)
        self.check('a range reaching back reads the union',
                   stored.query_range(date(2026, 1, 1), date(2026, 1, 15), None),
                   (date(2026, 1, 1), date(2026, 1, 20)))
        self.check('a range reaching forward reads the union',
                   stored.query_range(date(2026, 1, 15), date(2026, 1, 31), None),
                   (date(2026, 1, 10), date(2026, 1, 31)))
        self.check('a disjoint range reads the whole span',
                   stored.query_range(date(2026, 3, 1), date(2026, 3, 31), None),
                   (date(2026, 1, 10), date(2026, 3, 31)))

        stored.replace(date(2026, 1, 1), date(2026, 1, 20), self.candles(date(2026, 1, 1), 20))
        self.check('the widened copy replaced the narrower one', cache.writes, 2)
        self.check('the widened answer is sliced to the range asked for',
                   self.sliced(stored, date(2026, 1, 1), date(2026, 1, 15)),
                   [f'2026-01-{day:02d}' for day in range(1, 16)])

        widened = self.series_cache(cache)
        self.check('the widened copy is what is stored now',
                   (widened.from_date, widened.to_date), (date(2026, 1, 1), date(2026, 1, 20)))

    def widening_stops_at_the_intraday_span(self):
        """The union is not read when it would span more days than an intraday request may ask for.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        first = self.series_cache(cache)
        first.replace(date(2025, 6, 1), date(2025, 12, 31), self.candles(date(2025, 6, 1), 5))

        stored = self.series_cache(cache)
        self.check('a union within the span is read',
                   stored.query_range(date(2025, 12, 1), date(2026, 1, 5), 366),
                   (date(2025, 6, 1), date(2026, 1, 5)))
        self.check('a union one day past the span is refused',
                   stored.query_range(date(2026, 6, 2), date(2026, 6, 30), 366),
                   (date(2026, 6, 2), date(2026, 6, 30)))
        self.check('a union exactly at the span is read',
                   stored.query_range(date(2026, 6, 1), date(2026, 6, 1), 366),
                   (date(2025, 6, 1), date(2026, 6, 1)))
        self.check('a daily union is never refused',
                   stored.query_range(date(2026, 6, 2), date(2026, 6, 30), None),
                   (date(2025, 6, 1), date(2026, 6, 30)))

    def a_later_loader_run_discards_the_copy(self):
        """A copy built under an earlier price history run is thrown away.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run('2026-09-22 08:31:04')
        first = self.series_cache(cache)
        first.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10))

        cache.values['unified:prices:last_run'] = self.last_run('2026-09-23 08:29:51')
        stored = self.series_cache(cache)
        self.check('a copy from an earlier run is not loaded', stored.loaded, False)
        self.check('a copy from an earlier run covers nothing',
                   stored.covers(date(2026, 1, 1), date(2026, 1, 10)), False)
        self.check('a copy from an earlier run does not widen the read',
                   stored.query_range(date(2026, 1, 5), date(2026, 1, 6), None),
                   (date(2026, 1, 5), date(2026, 1, 6)))

    def other_columns_discard_the_copy(self):
        """A copy whose columns are not the ones the answer carries is thrown away.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        first = self.series_cache(cache, columns=ADJUSTED_COLUMNS, basis='unadjusted')
        first.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10, factor=1.0))

        stored = self.series_cache(cache, columns=DAILY_COLUMNS, basis='unadjusted')
        self.check('a copy with other columns is not loaded', stored.loaded, False)

    def an_unrecorded_run_still_caches(self):
        """A cache with no recorded price history run still stores and reads copies.

        Returns:
            None: This method returns nothing.
        """
        cache = StandInCache()
        first = self.series_cache(cache)
        first.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10))
        self.check('a copy is written with no run recorded', cache.writes, 1)

        stored = self.series_cache(cache)
        self.check('a copy is read back with no run recorded', stored.loaded, True)

    def an_unreadable_run_turns_the_cache_off(self):
        """A `last_run` value that cannot be read leaves the endpoint reading the database.

        Returns:
            None: This method returns nothing.
        """
        cache = StandInCache({'unified:prices:last_run': 'not json at all'})
        stored = self.series_cache(cache)
        stored.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10))
        self.check('nothing is stored when the run cannot be read', cache.writes, 0)
        self.check('the answer is still served', len(stored.candles), 10)

    def an_oversized_answer_is_not_stored(self):
        """An answer past the size cap is served and not stored, leaving any narrower copy in place.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        first = self.series_cache(cache)
        first.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10))

        stored = self.series_cache(cache)
        huge = self.candles(date(2020, 1, 1), 40000)
        self.check('the answer is past the cap', len(json.dumps(huge)) > MAXIMUM_ENTRY_BYTES, True)
        stored.replace(date(2020, 1, 1), date(2029, 5, 18), huge)
        self.check('an oversized answer is not stored', cache.writes, 1)
        self.check('an oversized answer is still served', len(stored.candles), 40000)

        kept = self.series_cache(cache)
        self.check('the narrower copy is left in place',
                   (kept.from_date, kept.to_date), (date(2026, 1, 1), date(2026, 1, 10)))

    def an_unreachable_redis_is_not_an_error(self):
        """A Redis that raises on every command leaves the endpoint reading the database.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        cache.fails = True
        stored = self.series_cache(cache)
        self.check('an unreachable Redis loads nothing', stored.loaded, False)
        self.check('an unreachable Redis covers nothing',
                   stored.covers(date(2026, 1, 1), date(2026, 1, 2)), False)
        stored.replace(date(2026, 1, 1), date(2026, 1, 10), self.candles(date(2026, 1, 1), 10))
        self.check('an unreachable Redis still serves the answer', len(stored.candles), 10)

    def each_basis_and_cut_off_has_its_own_key(self):
        """Adjusted, unadjusted and as-served prices, and each `known_as_of`, are cached apart.

        Returns:
            None: This method returns nothing.
        """
        cache = self.cache_with_run()
        adjusted = self.series_cache(cache, columns=ADJUSTED_COLUMNS, basis='adjusted')
        unadjusted = self.series_cache(cache, basis='unadjusted')
        as_served = self.series_cache(cache, basis='as_served')
        dated = self.series_cache(cache, columns=ADJUSTED_COLUMNS, basis='adjusted',
                                  known_as_of=date(2024, 1, 1))
        keys = [adjusted.key, unadjusted.key, as_served.key, dated.key]
        self.check('every basis and cut-off has its own key', len(set(keys)), 4)
        self.check('the adjusted key names the series and the cut-off',
                   dated.key,
                   'unified:prices:cache:a2c4e6f8-0000-4000-8000-000000000001:day:adjusted:2024-01-01')
        self.check('a key with every factor applied says so',
                   adjusted.key,
                   'unified:prices:cache:a2c4e6f8-0000-4000-8000-000000000001:day:adjusted:latest')


if __name__ == '__main__':
    sys.exit(PriceCacheSuite().run())
