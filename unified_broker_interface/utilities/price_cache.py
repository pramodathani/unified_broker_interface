"""
The Redis copy of the candles `/api/instruments/prices` has already read from the database.

Each series - one instrument, one interval, one price basis and one `known_as_of` - is kept under one
key holding the widest date range read for it so far. A later request whose range falls inside that
window is sliced out of the copy and no database query is made at all. A request reaching outside the
window is read from the union of the two ranges, and that wider answer replaces the copy, so a caller
that keeps asking for a longer history fills one growing entry rather than many overlapping ones.

**What makes a copy current.** A copy records the `finished` time of the `bin/unified/historical_prices`
run that was in force when it was built, read from `unified:prices:last_run`. When the loader has run
since - a nightly load, a correction, a rebuilt adjustment factor - the copy is ignored and written
again from the database. That is what keeps the promise the adjustment DDL makes, that correcting a
factor corrects every query at once: a stored copy of adjusted prices only outlives the factors it was
built from until the next run. A one day expiry is a backstop for anything the stamp cannot see, and a
copy whose columns are not the ones the answer now carries is ignored as well.

**What is not kept.** An entry larger than `MAXIMUM_ENTRY_BYTES` is served to the caller and then
dropped rather than stored, because a year of one minute bars is several megabytes and this Redis also
holds the live quote feed and the instrument catalogue. Any Redis or decoding failure means the request
is answered from the database, and is logged rather than raised.
"""

import json
import time
from datetime import date, datetime

from utilities.configurations import get_logger

logger = get_logger("rest_api.prices")

# The candles this API has served, and the price history run they were read under.
CACHE_KEY_PREFIX = "unified:prices:cache"
LAST_RUN_KEY = "unified:prices:last_run"

# How long a copy is kept, whatever the loader does, as the key's expiry.
ENTRY_TTL_SECONDS = 86400

# The largest entry worth keeping, as its serialized length.
MAXIMUM_ENTRY_BYTES = 2 * 1024 * 1024

# The stamp used while the loader has never recorded a run.
NO_RUN_RECORDED = "none"

def loader_stamp(last_run):
    """
    The identity of the price history run in force, as a stored copy records it.

    Args:
        last_run (str | None): The value of `unified:prices:last_run`, or None when it is unset.

    Returns:
        str | None: The run's `finished` time, `NO_RUN_RECORDED` when no run is recorded, or None when
            the value cannot be read, which turns the cache off for the request.
    """
    if last_run is None:
        return NO_RUN_RECORDED
    try:
        finished = json.loads(last_run).get("finished")
    except (ValueError, AttributeError):
        return None
    return finished or None

class PriceCache:
    """
    One series' cached candles: the copy Redis holds, and the wider copy that replaces it.

    The object is built for one request, `load()` reads Redis once, and the candles it then holds are
    either the stored copy or the rows the caller read from the database and handed to `replace()`.

    Attributes:
        cache (redis.Redis): The shared Redis client, decoding responses.
        key (str): The key this series is stored under.
        columns (list[str]): The column names the answer carries, which a stored copy must match.
        from_date (datetime.date | None): The first day the held candles cover, or None while none are held.
        to_date (datetime.date | None): The last day the held candles cover, or None while none are held.
        candles (list[list]): The held candles, oldest first, in the shape the endpoint sends them.
        loaded (bool): Whether the held candles came from Redis rather than from the database.
    """

    def __init__(self, cache, instrument_id, interval, basis, known_as_of, columns):
        """
        Name the series without reading anything.

        Args:
            cache (redis.Redis): The shared Redis client, decoding responses.
            instrument_id (str): The unified instrument id.
            interval (str): The stored interval name, for example "day" or "15minute".
            basis (str): The price basis, one of "adjusted", "unadjusted" and "as_served".
            known_as_of (datetime.date | None): The adjustment cut-off date, or None for every factor.
            columns (list[str]): The column names the answer carries.
        """
        self.cache = cache
        self.columns = list(columns)
        self.key = ":".join([
            CACHE_KEY_PREFIX,
            instrument_id,
            interval,
            basis,
            known_as_of.isoformat() if known_as_of is not None else "latest",
        ])
        self.from_date = None
        self.to_date = None
        self.candles = []
        self.loaded = False
        self._stamp = None

    def load(self):
        """
        Read the stored copy and the loader's stamp, keeping the copy only when it is still current.

        A failure to read or decode leaves nothing held, so the request falls through to the database.

        Returns:
            None: This method returns nothing.
        """
        try:
            pipeline = self.cache.pipeline()
            pipeline.get(self.key)
            pipeline.get(LAST_RUN_KEY)
            stored, last_run = pipeline.execute()
        except Exception as exception:
            logger.warning(f"the cached candles under {self.key} could not be read: {exception}")
            return

        self._stamp = loader_stamp(last_run)
        if self._stamp is None or not stored:
            return
        try:
            entry = json.loads(stored)
            if entry["last_run"] != self._stamp or entry["columns"] != self.columns:
                return
            from_date = date.fromisoformat(entry["from"])
            to_date = date.fromisoformat(entry["to"])
            candles = entry["candles"]
        except (ValueError, TypeError, KeyError) as error:
            logger.warning(f"the cached candles under {self.key} were not readable and are ignored: {error}")
            return

        self.from_date = from_date
        self.to_date = to_date
        self.candles = candles
        self.loaded = True

    def covers(self, from_date, to_date):
        """
        Whether a loaded copy holds every candle the request asks for.

        Args:
            from_date (datetime.date): The first day the request asks for.
            to_date (datetime.date): The last day the request asks for.

        Returns:
            bool: True when the request can be answered by slicing the loaded copy.
        """
        if not self.loaded:
            return False
        return self.from_date <= from_date and to_date <= self.to_date

    def query_range(self, from_date, to_date, maximum_days):
        """
        The range to read from the database, widened to the loaded copy's where that stays allowed.

        Reading the union of the two ranges costs one query instead of two and leaves one entry behind
        rather than two that overlap. It is not done when the union would span more days than the
        interval allows a caller to ask for, since that would turn a legal request into a far larger
        query than the endpoint would ever accept.

        Args:
            from_date (datetime.date): The first day the request asks for.
            to_date (datetime.date): The last day the request asks for.
            maximum_days (int | None): The longest range this interval may span, or None when unlimited.

        Returns:
            tuple[datetime.date, datetime.date]: The first and last day to read, both inclusive.
        """
        if self.from_date is None:
            return from_date, to_date
        widened_from = min(self.from_date, from_date)
        widened_to = max(self.to_date, to_date)
        if maximum_days is not None and (widened_to - widened_from).days > maximum_days:
            return from_date, to_date
        return widened_from, widened_to

    def replace(self, from_date, to_date, candles):
        """
        Hold the candles just read from the database, and store them for the next request.

        The copy is stamped with the loader run read in `load()`, before the query ran, so a run that
        finished while the query was in flight leaves a copy that the next request discards rather than
        one that claims to hold the newer prices.

        Args:
            from_date (datetime.date): The first day the candles cover.
            to_date (datetime.date): The last day the candles cover.
            candles (list[list]): The candles read, oldest first.

        Returns:
            None: This method returns nothing.
        """
        self.from_date = from_date
        self.to_date = to_date
        self.candles = candles
        self.loaded = False
        if self._stamp is None:
            return

        entry = json.dumps({
            "last_run": self._stamp,
            "built_at": time.time(),
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "columns": self.columns,
            "candles": candles,
        })
        if len(entry) > MAXIMUM_ENTRY_BYTES:
            logger.info(f"{len(candles)} candles for {self.key} are {len(entry)} bytes and are not cached")
            return
        try:
            self.cache.set(self.key, entry, ex=ENTRY_TTL_SECONDS)
        except Exception as exception:
            logger.warning(f"the candles for {self.key} were not cached: {exception}")

    def between(self, start, end):
        """
        The held candles whose time is at or after `start` and before `end`.

        The two boundaries are found by binary search, which parses about a dozen of the stored
        timestamps rather than all of them, so slicing a long series stays cheap.

        Args:
            start (datetime.datetime): The first instant to include, timezone aware.
            end (datetime.datetime): The first instant to leave out, timezone aware.

        Returns:
            list[list]: The candles in the period, oldest first.
        """
        if not self.candles:
            return []
        return self.candles[self._first_at_or_after(start):self._first_at_or_after(end)]

    def _first_at_or_after(self, moment):
        """
        The index of the first held candle stamped at or after an instant.

        Args:
            moment (datetime.datetime): The instant to find, timezone aware.

        Returns:
            int: The index, which is the number of held candles when every one is earlier.
        """
        low = 0
        high = len(self.candles)
        while low < high:
            middle = (low + high) // 2
            if datetime.fromisoformat(self.candles[middle][0]) < moment:
                low = middle + 1
            else:
                high = middle
        return low
