"""Offline checks of the lowest-cost broker selector and the broker cost table it reads.

The selector, the cost table, the rate budget and the daily order count are run against scripted table rows, scripted Redis counts and a stand-in database connection, so no Redis, database, credentials or network are used. The rows are the user's table of 2026-09-29, so the orderings checked here are the ones production sees on the first day.

Typical usage:

    python -m test_runs.broker_selection
"""

import datetime
import decimal
import logging
import sys

import psycopg2

from test_runs import redis_stand_ins
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.registry import (
    BROKER_ORDER_CLASSES,
)
from unified_broker_interface.utilities.broker_selection.lowest_cost import (
    LowestCostSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
    BrokerCostTable,
)
from unified_broker_interface.utilities.order_engine.utilities.daily_order_count import (
    DailyOrderCount,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)
from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    RateBudget,
)
from utilities import configurations

TABLE_ROWS = [
    ('dhan', 9, 480, 7000, None, 0, 20, 20),
    ('flattrade', 10, 180, None, None, 0, 0, 0),
    ('fyers', 8, 180, None, 100000, 0, 20, 20),
    ('groww', 9, 240, None, None, 20, 20, 20),
    ('indmoney', 7, 540, None, None, 20, 20, 20),
    ('kotak', 9, 600, None, None, 20, 20, 10),
    ('shoonya', 8, 540, None, None, 0, 5, 5),
    ('stoxkart', 6, 420, None, None, 0, 20, 20),
    ('wisdom_capital', 8, 540, None, None, 0, 0, 0),
    ('zerodha', 9, 375, None, 4500, 0, 20, 20),
]


class FixedDaySelector(LowestCostSelector):
    """The lowest-cost selector with the time of day fixed, so pacing gives the same answer on every run.

    Attributes:
        fixed_fraction (float): The share of the equity session that has passed.
    """

    def __init__(self, cost_table, fixed_fraction):
        """Builds the selector.

        Args:
            cost_table (BrokerCostTable): The table.
            fixed_fraction (float): The share of the equity session that has passed.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(cost_table)
        self.fixed_fraction = fixed_fraction

    def day_fraction(self, now=None):
        """The fixed share of the session.

        Args:
            now (datetime.datetime | None): Ignored.

        Returns:
            float: The fixed share.
        """
        del now
        return self.fixed_fraction


class RecordingPipeline:
    """A pipeline that only records the `eval` the selector queues.

    Attributes:
        evaluations (list): Each queued `eval` as `(script, key count, keys and arguments)`.
    """

    def __init__(self):
        """Builds an empty pipeline.

        Returns:
            None: This method returns nothing.
        """
        self.evaluations = []

    def eval(self, script, key_count, *keys_and_arguments):
        """Records one `eval`.

        Args:
            script (str): The Lua script.
            key_count (int): How many of the values are keys.
            *keys_and_arguments: The keys, then the arguments.

        Returns:
            RecordingPipeline: This pipeline.
        """
        self.evaluations.append((
            script,
            key_count,
            list(keys_and_arguments),
        ))
        return self


class StandInOrder:
    """An order carrying only the product the selector reads.

    Attributes:
        product (str): `CNC`, `MIS` or `NRML`.
    """

    def __init__(self, product):
        """Builds the order.

        Args:
            product (str): The product.

        Returns:
            None: This method returns nothing.
        """
        self.product = product


class StandInCursor:
    """A database cursor that answers every query with fixed rows.

    Attributes:
        rows (list): The rows to answer with.
    """

    def __init__(self, rows):
        """Builds the cursor.

        Args:
            rows (list): The rows to answer with.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Opens the cursor.

        Returns:
            StandInCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Closes the cursor.

        Args:
            exception_type (type | None): The exception's type, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (object | None): Its traceback.

        Returns:
            bool: False, so an exception is not swallowed.
        """
        del exception_type
        del exception
        del traceback
        return False

    def execute(self, query):
        """Accepts a query.

        Args:
            query (str): The query.

        Returns:
            None: This method returns nothing.
        """
        del query

    def fetchall(self):
        """Answers the fixed rows.

        Returns:
            list: The rows.
        """
        return list(self.rows)


class StandInConnection:
    """A database connection whose cursor answers fixed rows.

    Attributes:
        rows (list): The rows every query answers.
        closed (bool): Whether the connection has been closed.
    """

    def __init__(self, rows):
        """Builds the connection.

        Args:
            rows (list): The rows every query answers.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.closed = False

    def cursor(self):
        """Opens a cursor.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self.rows)

    def close(self):
        """Closes the connection.

        Returns:
            None: This method returns nothing.
        """
        self.closed = True


class StandInDatabase:
    """Stands in for `configurations.get_postgres`, answering fixed rows or failing to connect.

    Attributes:
        rows (list): The rows every query answers.
        fails (bool): Whether connecting raises `psycopg2.OperationalError`.
        connections (list): Every connection handed out.
    """

    def __init__(self, rows, fails=False):
        """Builds the database.

        Args:
            rows (list): The rows every query answers.
            fails (bool): Whether connecting fails.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.fails = fails
        self.connections = []

    def connect(self):
        """Hands out a connection, or fails the way an unreachable server does.

        Returns:
            StandInConnection: The connection.

        Raises:
            psycopg2.OperationalError: When the database is set to fail.
        """
        if self.fails:
            raise psycopg2.OperationalError('stand-in database is unreachable')
        connection = StandInConnection(self.rows)
        self.connections.append(connection)
        return connection


class BrokerSelectionSuite:
    """Runs every check and reports how many passed.

    Attributes:
        logger (logging.Logger): A logger that writes nothing, so a deliberate failure prints no traceback.
        rotation (list): Every broker's name, in the order the brokers take turns.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('test_runs.broker_selection')
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False
        self.rotation = []
        for broker_order_class in BROKER_ORDER_CLASSES:
            self.rotation.append(broker_order_class.BROKER_NAME)
        self.passed = 0
        self.failed = []

    def check(self, name, actual, expected):
        """Compares one value with what it should be, and prints the difference when they differ.

        Args:
            name (str): What is being checked.
            actual (object): The value produced.
            expected (object): The value it should be.

        Returns:
            None: This method returns nothing.
        """
        if actual == expected:
            self.passed = self.passed + 1
            return
        self.failed.append(name)
        print(f'FAILED  {name}')
        print(f'  expected: {expected!r}')
        print(f'  actual:   {actual!r}')

    def table_rows(self):
        """The user's table as the cost table holds it.

        Returns:
            dict: Each broker's `BrokerCosts`, by broker name.
        """
        rows = {}
        for row in TABLE_ROWS:
            rows[row[0]] = self.broker_costs(row)
        return rows

    def broker_costs(self, row):
        """One row of the table as a `BrokerCosts`.

        Args:
            row (tuple): The broker, four limits and three fees, in the table's column order.

        Returns:
            BrokerCosts: The row.
        """
        fees = {
            'delivery': decimal.Decimal(row[5]),
            'fno': decimal.Decimal(row[6]),
            'intraday': decimal.Decimal(row[7]),
        }
        return BrokerCosts(row[0], row[1], row[2], row[3], row[4], fees)

    def cost_table(self, extra_rows=None):
        """A cost table holding the user's rows and any extra ones.

        Args:
            extra_rows (list | None): More rows, as tuples in the table's column order.

        Returns:
            BrokerCostTable: The table.
        """
        rows = self.table_rows()
        for row in extra_rows or []:
            rows[row[0]] = self.broker_costs(row)
        return BrokerCostTable(self.logger, rows)

    def instrument(self, segment):
        """An instrument in a segment, with no order handles.

        Args:
            segment (str): The exchange-prefixed segment.

        Returns:
            Instrument: The instrument.
        """
        identity = {
            'segment': segment,
        }
        return Instrument('00000000-0000-4000-8000-000000000001', identity, {})

    def counts_reply(self, names, used):
        """The counts script's reply for scripted counts.

        Args:
            names (list): The broker names the script was queued for, in order.
            used (dict): Each broker's scripted counts, a dict by window, for the brokers that have any.

        Returns:
            list: The flat reply, four counts per broker.
        """
        reply = []
        for broker_name in names:
            counts = used.get(broker_name, {})
            reply.append(counts.get('second', 0))
            reply.append(counts.get('minute', 0))
            reply.append(counts.get('hour', 0))
            reply.append(counts.get('day', 0))
        return reply

    def ranked(self, selector, segment, product, used=None, rotation=None):
        """Queues the selector's counts and ranks the rotation with scripted counts.

        Args:
            selector (LowestCostSelector): The selector.
            segment (str): The instrument's segment.
            product (str): The order's product.
            used (dict | None): Each broker's scripted counts by window.
            rotation (list | None): The rotation, or None for every broker.

        Returns:
            list: The ranked broker names.
        """
        pipeline = RecordingPipeline()
        selector.queue_redis_commands(pipeline, StandInOrder(product), 'instrument')
        names = sorted(selector.cost_table.rows)
        replies = [
            self.counts_reply(names, used or {}),
        ]
        return selector.ranked_brokers(
            StandInOrder(product),
            self.instrument(segment),
            rotation or self.rotation,
            replies,
        )

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.each_order_has_the_right_category()
        self.futures_and_options_go_to_the_free_brokers_first()
        self.delivery_keeps_the_versatile_free_brokers_for_last()
        self.intraday_follows_the_intraday_prices()
        self.a_full_minute_puts_a_broker_last()
        self.pressure_shares_orders_between_equal_brokers()
        self.this_process_s_own_choices_count_before_redis_catches_up()
        self.a_daily_cap_is_paced_through_the_session()
        self.the_exit_reserve_blocks_new_orders()
        self.a_broker_without_a_row_goes_last()
        self.a_new_broker_is_only_a_new_row()
        self.a_reply_that_does_not_match_is_ignored()
        self.one_command_reads_every_count()
        self.the_table_is_read_from_the_database()
        self.an_empty_table_stops_the_start()
        self.a_failed_reload_keeps_the_old_table()
        self.the_reload_waits_for_six_in_the_morning()
        self.the_rate_budget_takes_its_limits_from_the_table()
        self.the_daily_count_takes_its_caps_from_the_table()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def each_order_has_the_right_category(self):
        """A future or option is `fno` whatever its product, and a cash order is `delivery` for CNC and `intraday` otherwise.

        Returns:
            None: This method returns nothing.
        """
        selector = LowestCostSelector(self.cost_table())
        self.check(
            'an equity option is fno',
            selector.category(StandInOrder('MIS'), self.instrument('nse_equity_options')),
            'fno',
        )
        self.check(
            'a commodity future is fno',
            selector.category(StandInOrder('NRML'), self.instrument('mcx_commodity_futures')),
            'fno',
        )
        self.check(
            'a CNC equity order is delivery',
            selector.category(StandInOrder('CNC'), self.instrument('nse_equities')),
            'delivery',
        )
        self.check(
            'an MIS equity order is intraday',
            selector.category(StandInOrder('MIS'), self.instrument('nse_equities')),
            'intraday',
        )

    def futures_and_options_go_to_the_free_brokers_first(self):
        """With nothing sent yet, an F&O order goes to the two free brokers, then the ₹5 one, then the ₹20 ones.

        Among the ₹20 brokers, the ones that save nothing on other kinds of order come first.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        self.check(
            'an F&O order is ranked by price, then by what each broker saves elsewhere',
            self.ranked(selector, 'nse_equity_options', 'NRML'),
            [
                'flattrade',
                'wisdom_capital',
                'shoonya',
                'groww',
                'indmoney',
                'kotak',
                'dhan',
                'fyers',
                'stoxkart',
                'zerodha',
            ],
        )

    def delivery_keeps_the_versatile_free_brokers_for_last(self):
        """Delivery is free at seven brokers, and the four that are free for nothing else are used first.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        self.check(
            'a delivery order spares the brokers other kinds of order need',
            self.ranked(selector, 'nse_equities', 'CNC'),
            [
                'dhan',
                'fyers',
                'stoxkart',
                'zerodha',
                'shoonya',
                'flattrade',
                'wisdom_capital',
                'groww',
                'indmoney',
                'kotak',
            ],
        )

    def intraday_follows_the_intraday_prices(self):
        """Intraday uses the intraday column, where Kotak's ₹10 puts it ahead of the ₹20 brokers.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        self.check(
            'an intraday order is ranked by the intraday prices',
            self.ranked(selector, 'nse_equities', 'MIS'),
            [
                'flattrade',
                'wisdom_capital',
                'shoonya',
                'kotak',
                'groww',
                'indmoney',
                'dhan',
                'fyers',
                'stoxkart',
                'zerodha',
            ],
        )

    def a_full_minute_puts_a_broker_last(self):
        """A broker whose minute is used up is still offered the order, but after every other broker.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        used = {
            'flattrade': {
                'minute': 180,
            },
        }
        ranked = self.ranked(selector, 'nse_equity_options', 'NRML', used)
        self.check('a full minute puts the broker last', ranked[-1], 'flattrade')
        self.check('the other free broker comes first', ranked[0], 'wisdom_capital')

    def pressure_shares_orders_between_equal_brokers(self):
        """Between two equally cheap brokers, the one with more of its minute left comes first.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        used = {
            'flattrade': {
                'minute': 90,
            },
            'wisdom_capital': {
                'minute': 100,
            },
        }
        ranked = self.ranked(selector, 'nse_equity_options', 'NRML', used)
        self.check(
            'half of 180 is fuller than 100 of 540',
            ranked[:2],
            [
                'wisdom_capital',
                'flattrade',
            ],
        )

    def this_process_s_own_choices_count_before_redis_catches_up(self):
        """Choices this process made but has not sent yet fill a broker's minute as surely as sent messages.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        for count in range(180):
            selector.record_chosen('flattrade')
        ranked = self.ranked(selector, 'nse_equity_options', 'NRML')
        self.check('180 choices fill the minute with Redis still at zero', ranked[-1], 'flattrade')
        self.check(
            'the choices are counted in each window',
            selector.chosen_counts('flattrade'),
            {
                'second': 180,
                'minute': 180,
                'hour': 180,
            },
        )

    def a_daily_cap_is_paced_through_the_session(self):
        """Early in the session a day's messages weigh more than the same number late in it.

        Returns:
            None: This method returns nothing.
        """
        used = {
            'dhan': {
                'minute': 240,
            },
            'fyers': {
                'minute': 90,
            },
            'stoxkart': {
                'minute': 210,
            },
            'zerodha': {
                'day': 1000,
            },
        }
        early = FixedDaySelector(self.cost_table(), 0.16)
        late = FixedDaySelector(self.cost_table(), 0.92)
        self.check(
            'at 10:15 Zerodha has sent more than its share of the day, so it comes after the half-full brokers',
            self.ranked(early, 'nse_equities', 'CNC', used)[:4],
            [
                'dhan',
                'fyers',
                'stoxkart',
                'zerodha',
            ],
        )
        self.check(
            'at 15:00 the same 1,000 messages leave Zerodha the emptiest',
            self.ranked(late, 'nse_equities', 'CNC', used)[:4],
            [
                'zerodha',
                'dhan',
                'fyers',
                'stoxkart',
            ],
        )
        zerodha = self.cost_table().costs('zerodha')
        zerodha_used = {
            'second': 0,
            'minute': 0,
            'hour': 0,
            'day': 1000,
        }
        self.check(
            'the paced allowance at 10:15 is the share of the day so far plus a tenth',
            round(early.pressure(zerodha, zerodha_used, 0.16), 4),
            round(1000 / (4500 * 0.26), 4),
        )
        self.check(
            'the allowance never exceeds the cap',
            round(late.pressure(zerodha, zerodha_used, 0.92), 4),
            round(1000 / 4500, 4),
        )
        clock = LowestCostSelector(self.cost_table())
        self.check(
            'the session has not started at 09:00',
            clock.day_fraction(datetime.datetime(2026, 9, 29, 9, 0, tzinfo=INDIA)),
            0.0,
        )
        self.check(
            'the session is half over at 12:22:30',
            clock.day_fraction(datetime.datetime(2026, 9, 29, 12, 22, 30, tzinfo=INDIA)),
            0.5,
        )
        self.check(
            'the session is over at 16:00',
            clock.day_fraction(datetime.datetime(2026, 9, 29, 16, 0, tzinfo=INDIA)),
            1.0,
        )

    def the_exit_reserve_blocks_new_orders(self):
        """A broker that has reached its cap less the exit reserve is put last, as the daily count would refuse it.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 1.0)
        entry_limit = 4500 - int(4500 * selector.exit_reserve)
        used = {
            'zerodha': {
                'day': entry_limit,
            },
        }
        ranked = self.ranked(selector, 'nse_equities', 'CNC', used)
        self.check('a broker at its entry limit goes last', ranked[-1], 'zerodha')

    def a_broker_without_a_row_goes_last(self):
        """A broker the table does not name is offered orders after every broker it does, even a blocked one.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        rotation = list(self.rotation) + [
            'unpriced_broker',
        ]
        used = {
            'flattrade': {
                'minute': 180,
            },
        }
        ranked = self.ranked(selector, 'nse_equity_options', 'NRML', used, rotation)
        self.check(
            'the unpriced broker comes after the blocked one',
            ranked[-2:],
            [
                'flattrade',
                'unpriced_broker',
            ],
        )

    def a_new_broker_is_only_a_new_row(self):
        """An eleventh broker added as a table row changes the ranking with no change to the selector.

        The new broker is free for F&O only, so it saves nothing elsewhere and is used before Flattrade and Wisdom Capital.

        Returns:
            None: This method returns nothing.
        """
        new_row = ('new_broker', 10, 600, None, None, 20, 0, 20)
        selector = FixedDaySelector(
            self.cost_table([
                new_row,
            ]),
            0.5,
        )
        rotation = list(self.rotation) + [
            'new_broker',
        ]
        ranked = self.ranked(selector, 'nse_equity_options', 'NRML', None, rotation)
        self.check(
            'the new free-for-F&O-only broker comes first',
            ranked[:3],
            [
                'new_broker',
                'flattrade',
                'wisdom_capital',
            ],
        )

    def a_reply_that_does_not_match_is_ignored(self):
        """A reply of the wrong length is read as no counts rather than misread.

        Returns:
            None: This method returns nothing.
        """
        selector = FixedDaySelector(self.cost_table(), 0.5)
        selector.queue_redis_commands(RecordingPipeline(), StandInOrder('NRML'), 'instrument')
        ranked = selector.ranked_brokers(
            StandInOrder('NRML'),
            self.instrument('nse_equity_options'),
            self.rotation,
            [
                [
                    180,
                    180,
                ],
            ],
        )
        self.check('a short reply leaves the no-usage order', ranked[0], 'flattrade')

    def one_command_reads_every_count(self):
        """The selector queues exactly one `eval` with four keys per broker and three window lengths.

        Returns:
            None: This method returns nothing.
        """
        selector = LowestCostSelector(self.cost_table())
        pipeline = RecordingPipeline()
        queued = selector.queue_redis_commands(pipeline, StandInOrder('CNC'), 'instrument')
        self.check('one command is queued', queued, 1)
        self.check('one eval reaches the pipeline', len(pipeline.evaluations), 1)
        script, key_count, keys_and_arguments = pipeline.evaluations[0]
        self.check('four keys per broker', key_count, 40)
        self.check(
            'the first broker\'s keys',
            keys_and_arguments[:4],
            [
                'unified:orders:rate:dhan',
                'unified:orders:rate:dhan:minute',
                'unified:orders:rate:dhan:hour',
                'unified:orders:daily_count:dhan',
            ],
        )
        self.check(
            'the window lengths in microseconds',
            keys_and_arguments[40:],
            [
                int(selector.second_window_seconds * 1000000),
                60000000,
                3600000000,
            ],
        )

    def stand_in_rows(self):
        """The user's table as the database answers it.

        Returns:
            list: One tuple per row, fees as decimals.
        """
        rows = []
        for row in TABLE_ROWS:
            rows.append((
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                decimal.Decimal(row[5]),
                decimal.Decimal(row[6]),
                decimal.Decimal(row[7]),
            ))
        return rows

    def with_database(self, database, action):
        """Runs an action with `configurations.get_postgres` replaced by a stand-in.

        Args:
            database (StandInDatabase): The stand-in.
            action (collections.abc.Callable): What to run.

        Returns:
            object: What the action returned.
        """
        original_get_postgres = configurations.get_postgres
        configurations.get_postgres = database.connect
        try:
            return action()
        finally:
            configurations.get_postgres = original_get_postgres

    def the_table_is_read_from_the_database(self):
        """Loading reads every row, closes its connection, and answers each broker's limits.

        Returns:
            None: This method returns nothing.
        """
        database = StandInDatabase(self.stand_in_rows())
        table = BrokerCostTable(self.logger)
        self.with_database(database, table.load)
        self.check('ten rows are loaded', len(table.rows), 10)
        self.check('the connection is closed', database.connections[0].closed, True)
        self.check('Zerodha\'s per-second limit', table.per_second_limit('zerodha'), 9)
        self.check('Fyers\'s per-day limit', table.per_day_limit('fyers'), 100000)
        self.check('a broker with no per-day limit', table.per_day_limit('dhan'), None)
        self.check('a broker with no row', table.per_second_limit('nobody'), None)
        self.check(
            'the brokers with a per-day limit',
            table.day_capped_brokers(),
            {
                'fyers': 100000,
                'zerodha': 4500,
            },
        )
        self.check('Kotak\'s intraday fee', table.costs('kotak').fee('intraday'), decimal.Decimal(10))

    def an_empty_table_stops_the_start(self):
        """An empty table raises, so a process does not start routing orders without costs.

        Returns:
            None: This method returns nothing.
        """
        table = BrokerCostTable(self.logger)
        try:
            self.with_database(StandInDatabase([]), table.load)
        except ValueError:
            self.check('an empty table raises ValueError', True, True)
            return
        self.check('an empty table raises ValueError', False, True)

    def a_failed_reload_keeps_the_old_table(self):
        """A reload that cannot reach the database keeps yesterday's rows, and a later one picks up changes.

        Returns:
            None: This method returns nothing.
        """
        table = BrokerCostTable(self.logger)
        self.with_database(StandInDatabase(self.stand_in_rows()), table.load)
        reloaded = self.with_database(StandInDatabase([], fails=True), table.reload_once)
        self.check('an unreachable database is a failed reload', reloaded, False)
        self.check('the old rows stay', len(table.rows), 10)
        changed_rows = self.stand_in_rows()
        changed_rows[9] = ('zerodha', 5, 375, None, 4500, decimal.Decimal(0), decimal.Decimal(20), decimal.Decimal(20))
        reloaded = self.with_database(StandInDatabase(changed_rows), table.reload_once)
        self.check('a reachable database reloads', reloaded, True)
        self.check('a changed row is picked up', table.per_second_limit('zerodha'), 5)

    def the_reload_waits_for_six_in_the_morning(self):
        """The reload waits until the next 06:00 IST.

        Returns:
            None: This method returns nothing.
        """
        table = BrokerCostTable(self.logger)
        self.check(
            'at 05:00 the reload is an hour away',
            table.seconds_until_reload(datetime.datetime(2026, 9, 29, 5, 0, tzinfo=INDIA)),
            3600.0,
        )
        self.check(
            'at 07:00 the reload is tomorrow',
            table.seconds_until_reload(datetime.datetime(2026, 9, 29, 7, 0, tzinfo=INDIA)),
            23 * 3600.0,
        )

    def the_rate_budget_takes_its_limits_from_the_table(self):
        """The table's per-second limit replaces the configured one, and its per-minute limit is enforced.

        Returns:
            None: This method returns nothing.
        """
        small_minute = ('small_minute_broker', 10, 3, None, None, 0, 0, 0)
        table = self.cost_table([
            small_minute,
        ])
        fake_redis = redis_stand_ins.FakeRedis()
        budget = RateBudget(fake_redis, 0, 10, 0, self.logger, 1.0, None, table)
        self.check('the table\'s per-second limit is used', budget.limit_for('zerodha'), 9.0)
        self.check('a broker the table does not name keeps the configured limit', budget.limit_for('nobody'), 10)
        waits = []
        for attempt in range(4):
            waits.append(budget.try_take('small_minute_broker') > 0)
        self.check(
            'the fourth message in a minute of three must wait',
            waits,
            [
                False,
                False,
                False,
                True,
            ],
        )
        counted_keys = []
        for key, moment in fake_redis.rate_log:
            if key not in counted_keys:
                counted_keys.append(key)
        self.check(
            'the minute window is counted beside the second',
            counted_keys,
            [
                'unified:orders:rate:small_minute_broker',
                'unified:orders:rate:small_minute_broker:minute',
            ],
        )
        unconfigured = RateBudget(fake_redis, 0, 10, 0, self.logger)
        self.check('without a table there are no longer windows', unconfigured.longer_windows_for('dhan'), [])

    def the_daily_count_takes_its_caps_from_the_table(self):
        """The table's per-day limit replaces a configured cap, and a configured cap still covers a broker the table does not cap.

        Returns:
            None: This method returns nothing.
        """
        table = self.cost_table()
        fake_redis = redis_stand_ins.FakeRedis()
        caps = {
            'zerodha': 3000,
            'groww': 100,
        }
        daily_count = DailyOrderCount(fake_redis, caps, 0.05, self.logger, table)
        self.check('the table\'s cap wins', daily_count.cap_for('zerodha'), 4500)
        self.check('a configured cap covers a broker the table leaves uncapped', daily_count.cap_for('groww'), 100)
        self.check('a broker capped nowhere', daily_count.cap_for('dhan'), None)
        self.check(
            'the caps as they stand now',
            daily_count.current_caps(),
            {
                'zerodha': 4500,
                'groww': 100,
                'fyers': 100000,
            },
        )
        self.check(
            'with no table and no configured caps there is no count',
            DailyOrderCount.from_configuration(fake_redis, self.logger),
            None,
        )
        self.check(
            'with a table there is always a count, so caps can arrive with a reload',
            type(DailyOrderCount.from_configuration(fake_redis, self.logger, table)).__name__,
            'DailyOrderCount',
        )


if __name__ == '__main__':
    sys.exit(BrokerSelectionSuite().run())
