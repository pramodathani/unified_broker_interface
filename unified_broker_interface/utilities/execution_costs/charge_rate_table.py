"""The taxes and fees the exchanges and the government charge on every trade, read from `unified.charge_rates` and held in memory."""

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
    category,
    stt_buy_rate,
    stt_sell_rate,
    exchange_rate,
    sebi_rate,
    stamp_buy_rate,
    gst_rate,
    checked_on
FROM unified.charge_rates
ORDER BY segment, category
"""


class ChargeRate:
    """One row of the charge rate table: every statutory charge on a trade, as a share of the trade's value.

    Brokerage is not part of the row, because it differs by broker and is kept in `unified.broker_order_costs`. GST is charged on the exchange charge, the SEBI fee and the brokerage, never on STT or stamp duty.

    Attributes:
        segment (str): The catalogue segment, such as `nse_equity_index_options`.
        category (str): `delivery`, `intraday` or `fno`, decided as the lowest-cost selector decides it.
        stt_buy_rate (decimal.Decimal): Securities transaction tax on the value bought.
        stt_sell_rate (decimal.Decimal): Securities transaction tax on the value sold.
        exchange_rate (decimal.Decimal): The exchange's transaction charge on the value bought and on the value sold.
        sebi_rate (decimal.Decimal): SEBI's turnover fee on the value bought and on the value sold.
        stamp_buy_rate (decimal.Decimal): Stamp duty on the value bought.
        gst_rate (decimal.Decimal): GST on the exchange charge, the SEBI fee and the brokerage.
        checked_on (datetime.date | None): The day the row was last checked against a broker's bill, or None when it never has been.
    """

    def __init__(
        self,
        segment,
        category,
        stt_buy_rate,
        stt_sell_rate,
        exchange_rate,
        sebi_rate,
        stamp_buy_rate,
        gst_rate,
        checked_on=None,
    ):
        """Builds one row.

        Args:
            segment (str): The catalogue segment.
            category (str): `delivery`, `intraday` or `fno`.
            stt_buy_rate (decimal.Decimal): STT on the value bought.
            stt_sell_rate (decimal.Decimal): STT on the value sold.
            exchange_rate (decimal.Decimal): The exchange's charge on each side.
            sebi_rate (decimal.Decimal): SEBI's fee on each side.
            stamp_buy_rate (decimal.Decimal): Stamp duty on the value bought.
            gst_rate (decimal.Decimal): GST on the exchange charge, the SEBI fee and the brokerage.
            checked_on (datetime.date | None): The day the row was checked against a bill, or None.

        Returns:
            None: This method returns nothing.
        """
        self.segment = segment
        self.category = category
        self.stt_buy_rate = stt_buy_rate
        self.stt_sell_rate = stt_sell_rate
        self.exchange_rate = exchange_rate
        self.sebi_rate = sebi_rate
        self.stamp_buy_rate = stamp_buy_rate
        self.gst_rate = gst_rate
        self.checked_on = checked_on

    def buy_side_rate(self):
        """Every charge on the value bought, with GST added where it applies.

        Returns:
            decimal.Decimal: STT on buys, stamp duty, and the exchange charge and SEBI fee with their GST.
        """
        taxed = (self.exchange_rate + self.sebi_rate) * (1 + self.gst_rate)
        return self.stt_buy_rate + self.stamp_buy_rate + taxed

    def sell_side_rate(self):
        """Every charge on the value sold, with GST added where it applies.

        Returns:
            decimal.Decimal: STT on sells, and the exchange charge and SEBI fee with their GST.
        """
        taxed = (self.exchange_rate + self.sebi_rate) * (1 + self.gst_rate)
        return self.stt_sell_rate + taxed


class ChargeRateTable:
    """The whole charge rate table, loaded once when a process starts and again every day at 06:00 IST.

    Building the table reads nothing, like the margin rate table, so a process that never calls `start` sees an empty table, which is how the offline suites run. A segment with no row has no known charges, and `rate` then answers None rather than guessing.

    The rows are held as one dictionary that a reload replaces in a single assignment, so a reader that takes `rows` once sees one whole table.

    Attributes:
        logger (logging.Logger): The logger.
        rows (dict): Each `ChargeRate`, keyed by a `(segment, category)` tuple.
        stop (threading.Event): Set to end the daily reload thread.
        reload_thread (threading.Thread | None): The daily reload thread, once started.
    """

    def __init__(self, logger, rows=None):
        """Builds the table, empty unless rows are given.

        Args:
            logger (logging.Logger): The logger.
            rows (list | None): `ChargeRate` rows to start with, for a caller that does not read the database.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logger
        self.rows = {}
        for charge_rate in rows or []:
            self.rows[(charge_rate.segment, charge_rate.category)] = charge_rate
        self.stop = threading.Event()
        self.reload_thread = None

    def is_loaded(self):
        """Whether the table holds any rows.

        Returns:
            bool: True once rows have been loaded or given.
        """
        return bool(self.rows)

    def category(self, instrument_kind, product):
        """Which category of charges a trade pays, by the same rule the lowest-cost selector prices brokerage by.

        Args:
            instrument_kind (str): The instrument's kind, `derivative` for a future or an option.
            product (str): The order's product, such as `CNC`, `MIS` or `NRML`.

        Returns:
            str: `fno` for a future or an option, `delivery` for a `CNC` order, and `intraday` otherwise.
        """
        if instrument_kind == 'derivative':
            return 'fno'
        if product == 'CNC':
            return 'delivery'
        return 'intraday'

    def rate(self, segment, category):
        """The row for a segment and category.

        Args:
            segment (str): The catalogue segment.
            category (str): `delivery`, `intraday` or `fno`.

        Returns:
            ChargeRate | None: The row, or None when the table has none, so the charges are not known.
        """
        return self.rows.get((segment, category))

    def load(self):
        """Reads the table from PostgreSQL and replaces the rows held in memory.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        self.rows = self.read_rows()

    def read_rows(self):
        """Reads every row of `unified.charge_rates`.

        Returns:
            dict: Each `ChargeRate`, keyed by a `(segment, category)` tuple.

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
            charge_rate = ChargeRate(
                fetched_row[0],
                fetched_row[1],
                fetched_row[2],
                fetched_row[3],
                fetched_row[4],
                fetched_row[5],
                fetched_row[6],
                fetched_row[7],
                fetched_row[8],
            )
            rows[(charge_rate.segment, charge_rate.category)] = charge_rate
        return rows

    def start(self):
        """Loads the table and starts the thread that reloads it every day at 06:00 IST.

        An empty table is not an error: every lookup then answers None, and a warning says so.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        self.load()
        if not self.rows:
            self.logger.warning(
                'unified.charge_rates is empty, so no trade\'s taxes and fees are known; apply the mapping DDL to seed it.'
            )
        if self.reload_thread is not None:
            return
        self.reload_thread = threading.Thread(
            target=self.reload_every_day,
            name='charge-rate-table-reload',
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
                'The charge rate table could not be reloaded, so yesterday\'s rates stay in use.'
            )
            return False
        self.logger.info(f'Reloaded the charge rate table: {len(self.rows)} rows.')
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
