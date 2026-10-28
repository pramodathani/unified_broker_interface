"""Offline checks of the daily order snapshot: reading the combined orders document, choosing a day's orders, building rows, writing them and summarising them.

The orders are scripted in the shape `unified:orders:orders` held on 19 October 2026, including Flattrade's stop order 26101900306429, which filled at 160.45 while the strategy was cancelling it, and a Wisdom Capital cancellation whose message carries a carriage return. A stand-in Redis and a stand-in database are used, so no Redis, PostgreSQL, credentials or network are needed.

Typical usage:

    python -m test_runs.daily_orders
"""

import datetime
import decimal
import json
import logging
import sys

from unified_broker_interface.utilities.order_history.daily_order_snapshot import (
    ROW_COLUMNS,
    DailyOrderSnapshot,
)

DAY = datetime.date(2026, 10, 19)


class StandInCache:
    """A Redis stand-in holding string keys.

    Attributes:
        values (dict): Each key (str) to its value (bytes).
    """

    def __init__(self, values=None):
        """Builds the cache.

        Args:
            values (dict | None): The keys and values to start with.

        Returns:
            None: This method returns nothing.
        """
        self.values = dict(values or {})

    def get(self, key):
        """Reads a key.

        Args:
            key (str): The key.

        Returns:
            bytes | None: Its value, or None when it is missing.
        """
        return self.values.get(key)


class StandInSnapshotDatabase:
    """A database stand-in that records the statements and rows a snapshot writes.

    Attributes:
        statements (list): The first word of every statement, in order.
        deleted (list): The parameters each delete was given.
        written (list): The rows the insert was given, as lists.
        insert (str | None): The insert statement.
    """

    def __init__(self):
        """Builds the database.

        Returns:
            None: This method returns nothing.
        """
        self.statements = []
        self.deleted = []
        self.written = []
        self.insert = None

    def connect(self):
        """Opens a connection to this database.

        Returns:
            StandInSnapshotDatabase: This object, which is its own connection and cursor.
        """
        return self

    def cursor(self):
        """A cursor on this database.

        Returns:
            StandInSnapshotDatabase: This object.
        """
        return self

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            StandInSnapshotDatabase: This object.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Leaves the `with` block without suppressing an exception.

        Args:
            error_type (type | None): The exception's type.
            error (BaseException | None): The exception.
            traceback (types.TracebackType | None): The traceback.

        Returns:
            bool: False.
        """
        del error_type
        del error
        del traceback
        return False

    def execute(self, statement, parameters=None):
        """Records a statement.

        Args:
            statement (str): The SQL.
            parameters (tuple | None): Its parameters.

        Returns:
            None: This method returns nothing.
        """
        text = statement.strip()
        self.statements.append(text.split()[0])
        if text.startswith('DELETE'):
            self.deleted.append(parameters)

    def executemany(self, statement, rows):
        """Records an insert's rows.

        Args:
            statement (str): The SQL.
            rows (list): The rows.

        Returns:
            None: This method returns nothing.
        """
        self.statements.append(statement.split()[0])
        self.insert = statement
        for row in rows:
            self.written.append(list(row))

    def commit(self):
        """Commits nothing.

        Returns:
            None: This method returns nothing.
        """

    def rollback(self):
        """Rolls back nothing.

        Returns:
            None: This method returns nothing.
        """

    def close(self):
        """Closes nothing.

        Returns:
            None: This method returns nothing.
        """


class DailyOrdersSuite:
    """Runs every check and reports how many passed.

    Attributes:
        logger (logging.Logger): A logger that writes nothing.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('test_runs.daily_orders')
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False
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

    def document(self):
        """A combined orders document with three orders of 19 October and one of the day before.

        Returns:
            dict: The document.
        """
        return {
            'orders': [
                {
                    'broker': 'flattrade',
                    'order_id': '26101900306429',
                    'exchange_order_id': '1300000184687813',
                    'status': 'COMPLETE',
                    'status_message': 'SAF:order is not open to cancel',
                    'tradingsymbol': 'NIFTY27OCT26P22900',
                    'exchange': 'NFO',
                    'transaction_type': 'SELL',
                    'product': 'NRML',
                    'order_type': 'LIMIT',
                    'quantity': 65,
                    'filled_quantity': 65,
                    'price': 160.25,
                    'trigger_price': None,
                    'average_price': 160.45,
                    'order_timestamp': '2026-10-19T13:17:41+05:30',
                    'exchange_timestamp': '2026-10-19T13:17:40+05:30',
                    'instrument_id': '0180a843-ec35-5e61-b0a2-31e2b02bbaf9',
                    'engine_parent_id': '6b7bf82f-2c16-453f-b812-902216e84f4f',
                    'leg_role': 'root',
                },
                {
                    'broker': 'flattrade',
                    'order_id': '26101900383254',
                    'status': 'REJECTED',
                    'status_message': 'RED:Margin Shortfall',
                    'transaction_type': 'SELL',
                    'quantity': 65,
                    'filled_quantity': None,
                    'average_price': None,
                    'order_timestamp': '2026-10-19T14:23:55+05:30',
                },
                {
                    'broker': 'wisdom_capital',
                    'order_id': 'W-1',
                    'status': 'CANCELLED',
                    'status_message': '16388 : When Preopen unmatched orders are cancelled\r\nby the system',
                    'transaction_type': 'BUY',
                    'quantity': 10.0,
                    'filled_quantity': 0,
                    'order_timestamp': '2026-10-19T09:08:00+05:30',
                },
                {
                    'broker': 'zerodha',
                    'order_id': 'Z-1',
                    'status': 'COMPLETE',
                    'transaction_type': 'BUY',
                    'quantity': 1,
                    'filled_quantity': 1,
                    'average_price': 500,
                    'order_timestamp': '2026-10-18T23:40:00+05:30',
                },
                {
                    'broker': 'zerodha',
                    'order_id': 'Z-2',
                    'status': 'OPEN',
                    'order_timestamp': None,
                },
            ],
        }

    def snapshot(self, database=None, cache_values=None):
        """A snapshot over a stand-in cache holding the document, and a stand-in database.

        Args:
            database (StandInSnapshotDatabase | None): The database, or None for a new one.
            cache_values (dict | None): The cache's keys, or None for the scripted document.

        Returns:
            DailyOrderSnapshot: The snapshot.
        """
        if cache_values is None:
            cache_values = {'unified:orders:orders': json.dumps(self.document()).encode()}
        database = database or StandInSnapshotDatabase()
        return DailyOrderSnapshot(StandInCache(cache_values), database.connect, self.logger)

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.the_document_is_read_or_missing()
        self.orders_are_kept_by_their_day_in_india()
        self.a_row_reads_numbers_and_moments()
        self.the_write_replaces_the_day()
        self.the_summary_counts_fills_and_value()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def the_document_is_read_or_missing(self):
        """The document is read from bytes, and a missing key reads as None.

        Returns:
            None: This method returns nothing.
        """
        self.check('read', len(self.snapshot().read_document()['orders']), 5)
        self.check('missing', self.snapshot(cache_values={}).read_document(), None)

    def orders_are_kept_by_their_day_in_india(self):
        """The document's days are 18 and 19 October, and the 19th has three orders; an order without a time has no day.

        Returns:
            None: This method returns nothing.
        """
        snapshot = self.snapshot()
        document = snapshot.read_document()
        self.check('days', snapshot.trading_days(document), [datetime.date(2026, 10, 18), DAY])
        orders = snapshot.orders_of_day(document, DAY)
        identifiers = []
        for order in orders:
            identifiers.append(order['order_id'])
        self.check('orders of the day', identifiers, ['26101900306429', '26101900383254', 'W-1'])
        self.check('no time', snapshot.trading_day_of({'order_timestamp': 'not a time'}), None)
        self.check('no document', (snapshot.trading_days(None), snapshot.orders_of_day(None, DAY)), ([], []))

    def a_row_reads_numbers_and_moments(self):
        """A row holds prices as decimals, quantities as whole numbers, moments with their offset, and the whole order as JSON.

        Returns:
            None: This method returns nothing.
        """
        snapshot = self.snapshot()
        orders = snapshot.orders_of_day(snapshot.read_document(), DAY)
        row = snapshot.row(orders[0], DAY)
        self.check('row: columns', list(row), ROW_COLUMNS)
        self.check('row: fill', (row['filled_quantity'], row['average_price'], row['price']), (65, decimal.Decimal('160.45'), decimal.Decimal('160.25')))
        self.check('row: parent', (row['engine_parent_id'], row['leg_role']), ('6b7bf82f-2c16-453f-b812-902216e84f4f', 'root'))
        india = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        self.check('row: moment', row['order_timestamp'], datetime.datetime(2026, 10, 19, 13, 17, 41, tzinfo=india))
        self.check('row: order kept whole', json.loads(row['order'])['exchange_order_id'], '1300000184687813')
        rejected = snapshot.row(orders[1], DAY)
        self.check('row: no fill', (rejected['filled_quantity'], rejected['average_price'], rejected['engine_parent_id']), (None, None, None))
        cancelled = snapshot.row(orders[2], DAY)
        self.check('row: quantity rounded', cancelled['quantity'], 10)
        self.check('row: carriage return kept', '\r' in cancelled['status_message'], True)
        self.check('row: bad number', (snapshot.number('abc'), snapshot.whole(None)), (None, None))

    def the_write_replaces_the_day(self):
        """Writing runs the DDL, deletes the day and inserts its three orders with parameters, so no character needs escaping.

        Returns:
            None: This method returns nothing.
        """
        database = StandInSnapshotDatabase()
        snapshot = self.snapshot(database)
        orders = snapshot.orders_of_day(snapshot.read_document(), DAY)
        written = snapshot.write(DAY, orders)
        self.check('write: count', written, 3)
        self.check('write: statements', database.statements, ['CREATE', 'DELETE', 'INSERT'])
        self.check('write: day deleted', database.deleted, [(DAY,)])
        self.check('write: parameters', '%s' in database.insert and 'ON CONFLICT' in database.insert, True)
        self.check('write: first order', database.written[0][2], '26101900306429')

    def the_summary_counts_fills_and_value(self):
        """The 19th has two Flattrade orders, one filled for 10,429.25, and one Wisdom Capital order with no fill.

        Returns:
            None: This method returns nothing.
        """
        snapshot = self.snapshot()
        orders = snapshot.orders_of_day(snapshot.read_document(), DAY)
        lines = snapshot.summary(orders)
        figures = []
        for line in lines:
            figures.append((line['broker'], line['orders'], line['filled'], line['filled_value']))
        self.check('summary', figures, [('flattrade', 2, 1, decimal.Decimal('10429.25')), ('wisdom_capital', 1, 0, decimal.Decimal(0))])


if __name__ == '__main__':
    sys.exit(DailyOrdersSuite().run())
