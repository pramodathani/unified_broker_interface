"""The exchange's margin rates per segment and underlying, read from `unified.margin_rates` and held in memory."""

import datetime
import threading

from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
    RESET_HOUR,
)
from utilities import configurations

SELECT_RATES = """
SELECT
    segment,
    underlying,
    span_rate,
    exposure_rate
FROM unified.margin_rates
ORDER BY segment, underlying
"""


class MarginRate:
    """One row of the margin rate table: the share of a contract's value the exchange blocks as margin.

    Attributes:
        segment (str): The catalogue segment, such as `nse_equity_index_options`.
        underlying (str): The underlying symbol the row is for, or an empty string for every underlying in the segment.
        span_rate (decimal.Decimal): SPAN for a derivative, or the VaR margin for an intraday equity order.
        exposure_rate (decimal.Decimal): The exposure margin.
    """

    def __init__(self, segment, underlying, span_rate, exposure_rate):
        """Builds one row.

        Args:
            segment (str): The catalogue segment.
            underlying (str): The underlying symbol, or an empty string.
            span_rate (decimal.Decimal): The SPAN or VaR rate.
            exposure_rate (decimal.Decimal): The exposure rate.

        Returns:
            None: This method returns nothing.
        """
        self.segment = segment
        self.underlying = underlying
        self.span_rate = span_rate
        self.exposure_rate = exposure_rate

    def total_rate(self):
        """The whole margin as a share of a contract's value.

        Returns:
            decimal.Decimal: SPAN or VaR plus exposure.
        """
        return self.span_rate + self.exposure_rate


class MarginRateTable:
    """The whole margin rate table, loaded once when a process starts and again every day at 06:00 IST.

    Building the table reads nothing, like the broker cost table, so importing the REST API's blueprints needs no database. The process calls `start` once it is running. Until then the table is empty, and the lowest-cost selector's funds check stays off, which is also how the offline suites run.

    The rows are held as one dictionary that a reload replaces in a single assignment, so a reader that takes `rows` once sees one whole table.

    Attributes:
        logger (logging.Logger): The logger.
        rows (dict): Each `MarginRate`, keyed by a `(segment, underlying)` tuple.
        stop (threading.Event): Set to end the daily reload thread.
        reload_thread (threading.Thread | None): The daily reload thread, once started.
    """

    def __init__(self, logger, rows=None):
        """Builds the table, empty unless rows are given.

        Args:
            logger (logging.Logger): The logger.
            rows (list | None): `MarginRate` rows to start with, for a caller that does not read the database.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logger
        self.rows = {}
        for margin_rate in rows or []:
            self.rows[(margin_rate.segment, margin_rate.underlying)] = margin_rate
        self.stop = threading.Event()
        self.reload_thread = None

    def is_loaded(self):
        """Whether the table holds any rows.

        Returns:
            bool: True once rows have been loaded or given.
        """
        return bool(self.rows)

    def rate(self, segment, underlying):
        """The rate for a segment and underlying, falling back to the segment's own row.

        Args:
            segment (str): The catalogue segment.
            underlying (str | None): The underlying symbol, or None for an instrument without one.

        Returns:
            MarginRate | None: The underlying's row, else the segment's row, else None.
        """
        rows = self.rows
        if underlying:
            named = rows.get((segment, underlying))
            if named is not None:
                return named
        return rows.get((segment, ''))

    def load(self):
        """Reads the table from PostgreSQL and replaces the rows held in memory.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        self.rows = self.read_rows()

    def read_rows(self):
        """Reads every row of `unified.margin_rates`.

        Returns:
            dict: Each `MarginRate`, keyed by a `(segment, underlying)` tuple.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        connection = configurations.get_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.execute(SELECT_RATES)
                fetched = cursor.fetchall()
        finally:
            connection.close()
        rows = {}
        for fetched_row in fetched:
            margin_rate = MarginRate(
                fetched_row[0],
                fetched_row[1] or '',
                fetched_row[2],
                fetched_row[3],
            )
            rows[(margin_rate.segment, margin_rate.underlying)] = margin_rate
        return rows

    def start(self):
        """Loads the table and starts the thread that reloads it every day at 06:00 IST.

        An empty table is not an error: it leaves the funds check off, and a warning says so.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        self.load()
        if not self.rows:
            self.logger.warning(
                'unified.margin_rates is empty, so the lowest-cost selector does not check that a broker can afford an order; apply the mapping DDL to seed it.'
            )
        if self.reload_thread is not None:
            return
        self.reload_thread = threading.Thread(
            target=self.reload_every_day,
            name='margin-rate-table-reload',
            daemon=True,
        )
        self.reload_thread.start()

    def reload_every_day(self):
        """Waits until each 06:00 IST and reloads the table, keeping the old rows when a reload fails.

        Returns:
            None: This method returns nothing.
        """
        while not self.stop.wait(self.seconds_until_reload()):
            self.reload_once()

    def reload_once(self):
        """Reloads the table, keeping the rows already held when the reload fails.

        Returns:
            bool: True when the table was reloaded.
        """
        try:
            self.load()
        except Exception:
            self.logger.exception(
                'The margin rate table could not be reloaded, so yesterday\'s rates stay in use.'
            )
            return False
        self.logger.info(f'Reloaded the margin rate table: {len(self.rows)} rows.')
        return True

    def seconds_until_reload(self, now=None):
        """How long until the next 06:00 IST.

        Args:
            now (datetime.datetime | None): The moment to reckon from, or None for now in IST.

        Returns:
            float: Seconds until the next reload.
        """
        now = now or datetime.datetime.now(INDIA)
        reload_at = now.replace(
            hour=RESET_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
        if reload_at <= now:
            reload_at = reload_at + datetime.timedelta(days=1)
        return (reload_at - now).total_seconds()
