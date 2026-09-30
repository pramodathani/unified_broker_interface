"""Each broker's brokerage and order-rate limits, read from `unified.broker_order_costs` and held in memory."""

import datetime
import threading

from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
    RESET_HOUR,
)
from utilities import configurations

SELECT_COSTS = """
SELECT
    broker,
    orders_per_sec,
    orders_per_minute,
    orders_per_hour,
    orders_per_day,
    brokerage_for_delivery,
    brokerage_for_fno,
    brokerage_for_intraday,
    margin_multiplier_intraday,
    margin_multiplier_fno,
    margin_multiplier_commodity,
    gives_hedge_benefit
FROM unified.broker_order_costs
ORDER BY broker
"""


class BrokerCosts:
    """One broker's row of the cost table.

    Attributes:
        broker_name (str): The broker's name, as the code spells it.
        orders_per_second (int | None): Order messages allowed in any one second, or None for no limit.
        orders_per_minute (int | None): Order messages allowed in any one minute, or None for no limit.
        orders_per_hour (int | None): Order messages allowed in any one hour, or None for no limit.
        orders_per_day (int | None): Order messages allowed in one trading day, or None for no limit.
        fees (dict): The brokerage for one order (decimal.Decimal), by category: `delivery`, `fno` and `intraday`.
        margin_multipliers (dict): How much more than the exchange's margin the broker charges (decimal.Decimal, or None when not measured), by margin category: `intraday`, `fno` and `commodity`.
        gives_hedge_benefit (bool | None): Whether the broker prices several legs together for less than their sum, or None when not known.
    """

    def __init__(
        self,
        broker_name,
        orders_per_second,
        orders_per_minute,
        orders_per_hour,
        orders_per_day,
        fees,
        margin_multipliers=None,
        gives_hedge_benefit=None,
    ):
        """Builds one row.

        Args:
            broker_name (str): The broker's name.
            orders_per_second (int | None): The per-second limit, or None.
            orders_per_minute (int | None): The per-minute limit, or None.
            orders_per_hour (int | None): The per-hour limit, or None.
            orders_per_day (int | None): The per-day limit, or None.
            fees (dict): The brokerage (decimal.Decimal) by category.
            margin_multipliers (dict | None): The margin multipliers (decimal.Decimal or None) by margin category, or None when none are known.
            gives_hedge_benefit (bool | None): Whether the broker gives hedge benefit, or None when not known.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.orders_per_second = orders_per_second
        self.orders_per_minute = orders_per_minute
        self.orders_per_hour = orders_per_hour
        self.orders_per_day = orders_per_day
        self.fees = fees
        self.margin_multipliers = dict(margin_multipliers or {})
        self.gives_hedge_benefit = gives_hedge_benefit

    def fee(self, category):
        """The brokerage for one order of a category.

        Args:
            category (str): `delivery`, `fno` or `intraday`.

        Returns:
            decimal.Decimal: The brokerage.
        """
        return self.fees[category]

    def margin_multiplier(self, margin_category):
        """How much more than the exchange's margin the broker charges for a category, when that has been measured.

        Args:
            margin_category (str): `delivery`, `intraday`, `fno` or `commodity`. A delivery order is paid in full, so it has no multiplier.

        Returns:
            decimal.Decimal | int | None: The multiplier, 1 for `delivery`, or None when it has not been measured.
        """
        if margin_category == 'delivery':
            return 1
        return self.margin_multipliers.get(margin_category)


class BrokerCostTable:
    """The whole cost table, loaded once when a process starts and again every day at 06:00 IST.

    Building the table reads nothing, so importing the REST API's blueprints needs no database. The process calls `start` once it is running: the order engine does so when it starts, and `api.py` once every blueprint is mounted. Until then the table is empty, and everything that reads it falls back to configuration, which is also how the offline suites run.

    The rows are held as one dictionary that a reload replaces in a single assignment, so a reader that takes `rows` once sees one whole day's table and never a table half loaded. Nothing here reads the database while an order is being placed.

    Attributes:
        CATEGORIES (list): The three kinds of order the table prices.
        logger (logging.Logger): The logger.
        rows (dict): Each broker's `BrokerCosts`, by broker name.
        stop (threading.Event): Set to end the daily reload thread.
        reload_thread (threading.Thread | None): The daily reload thread, once started.
    """

    CATEGORIES = [
        'delivery',
        'fno',
        'intraday',
    ]

    def __init__(self, logger, rows=None):
        """Builds the table, empty unless rows are given.

        Args:
            logger (logging.Logger): The logger.
            rows (dict | None): Rows to start with, by broker name, for a caller that does not read the database.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logger
        self.rows = dict(rows or {})
        self.stop = threading.Event()
        self.reload_thread = None

    def load(self):
        """Reads the table from PostgreSQL and replaces the rows held in memory.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read, which a later try may get past.
            ValueError: When the table is empty, so a process that starts without costs stops rather than routing orders blind.
        """
        rows = self.read_rows()
        if not rows:
            raise ValueError('unified.broker_order_costs is empty; apply the mapping DDL to seed it')
        self.rows = rows

    def read_rows(self):
        """Reads every row of `unified.broker_order_costs`.

        Returns:
            dict: Each broker's `BrokerCosts`, by broker name.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        connection = configurations.get_postgres()
        try:
            with connection.cursor() as cursor:
                cursor.execute(SELECT_COSTS)
                fetched = cursor.fetchall()
        finally:
            connection.close()
        rows = {}
        for fetched_row in fetched:
            broker_name = fetched_row[0]
            fees = {
                'delivery': fetched_row[5],
                'fno': fetched_row[6],
                'intraday': fetched_row[7],
            }
            margin_multipliers = {
                'intraday': self.optional_column(fetched_row, 8),
                'fno': self.optional_column(fetched_row, 9),
                'commodity': self.optional_column(fetched_row, 10),
            }
            rows[broker_name] = BrokerCosts(
                broker_name,
                fetched_row[1],
                fetched_row[2],
                fetched_row[3],
                fetched_row[4],
                fees,
                margin_multipliers,
                self.optional_column(fetched_row, 11),
            )
        return rows

    @staticmethod
    def optional_column(fetched_row, position):
        """One column of a fetched row, or None when the row is shorter than that.

        A row read before the margin columns were added, or from a caller that builds rows by hand, has only the first eight columns.

        Args:
            fetched_row (tuple): The row.
            position (int): The column's position.

        Returns:
            object: The value, or None.
        """
        if len(fetched_row) <= position:
            return None
        return fetched_row[position]

    def costs(self, broker_name):
        """One broker's row.

        Args:
            broker_name (str): The broker.

        Returns:
            BrokerCosts | None: The row, or None when the table has no row for the broker.
        """
        return self.rows.get(broker_name)

    def per_second_limit(self, broker_name):
        """The broker's per-second limit from the table.

        Args:
            broker_name (str): The broker.

        Returns:
            int | None: The limit, or None when the table has no row or no per-second limit for the broker.
        """
        costs = self.rows.get(broker_name)
        if costs is None:
            return None
        return costs.orders_per_second

    def per_day_limit(self, broker_name):
        """The broker's per-day limit from the table.

        Args:
            broker_name (str): The broker.

        Returns:
            int | None: The limit, or None when the table has no row or no per-day limit for the broker.
        """
        costs = self.rows.get(broker_name)
        if costs is None:
            return None
        return costs.orders_per_day

    def day_capped_brokers(self):
        """Each broker the table gives a per-day limit, with that limit.

        Returns:
            dict: The per-day limit (int) by broker name.
        """
        caps = {}
        for broker_name, costs in self.rows.items():
            if costs.orders_per_day is not None:
                caps[broker_name] = costs.orders_per_day
        return caps

    def start(self, broker_names):
        """Loads the table and starts the thread that reloads it every day at 06:00 IST.

        Args:
            broker_names (list): Every broker orders can be placed at, so one the table has no row for can be named in a warning.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read.
            ValueError: When the table is empty.
        """
        self.load()
        for broker_name in broker_names:
            if broker_name not in self.rows:
                self.logger.warning(
                    f'unified.broker_order_costs has no row for {broker_name}, '
                    'so its configured rate limits apply and the lowest-cost '
                    'selector offers it orders only after every broker that has a row.'
                )
        if self.reload_thread is not None:
            return
        self.reload_thread = threading.Thread(
            target=self.reload_every_day,
            name='broker-cost-table-reload',
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
                'The broker cost table could not be reloaded, so yesterday\'s costs and limits stay in use.'
            )
            return False
        self.logger.info(f'Reloaded the broker cost table: {len(self.rows)} brokers.')
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
