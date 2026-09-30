"""Stores one day's instrument master with `ingest` and checks its row count against earlier days.

`ingest` is the whole daily job for one broker: it skips a date already stored, downloads the file, runs the cleaning steps, refuses a column the table does not have, and appends the rows to `<broker>.instruments` with the snapshot's `download_date`. `has_data_for` says whether a date is already stored, `table_columns` reads the table's columns from the database itself, and `check_row_count_deviation` compares a day's row count with the average of every earlier day, reporting but never raising, because a file that suddenly shrinks or grows is worth a look rather than a failed job.

The real engine points at TimescaleDB. This program replaces it with an in-memory SQLite database, `InMemoryInstrumentDatabase`, arranged to answer the same SQL: the broker's schema is an attached database named `demo`, a second attached database named `information_schema` holds a `columns` table describing `demo.instruments`, and a small SQL function stands in for PostgreSQL's `to_regclass`. The table already holds two earlier snapshots, of four and five rows. `DemoInstruments` is a made-up broker whose master file is held in memory, so nothing is downloaded.

Notice that the second `ingest` of the same date is skipped, that `bootstrap=True` replaces the stored rows instead, and that three rows against an average of four and a half is an alarm at the default ten percent but not at fifty.

Run it from the project root:

    python examples/stock_brokers/instruments/base/BrokerInstruments/example_2_storing_daily_snapshots.py
"""

import datetime
import io
import sqlite3

import pandas
import sqlalchemy
import sqlalchemy.pool

from stock_brokers.instruments.base import (
    BrokerInstruments,
)

MASTER_FILE = (
    'Exchange,Trading Symbol,Series,Lot Size\n'
    'NSE,INFY,EQ,1\n'
    'BSE,INFY,A,1\n'
    'NSE,TCS,EQ,1\n'
)

TABLE_COLUMNS = [
    'exchange',
    'trading_symbol',
    'series',
    'lot_size',
    'download_date',
]


class DemoInstruments(BrokerInstruments):
    """A made-up broker's instrument ingester whose master file is held in memory."""

    BROKER_NAME = 'demo'
    DEDUPE_KEY_COLUMNS = [
        'exchange',
        'trading_symbol',
    ]
    DEDUPE_SORT_COLUMN = 'series'

    def download(self):
        """Reads the master file, every value as text, as a real ingester reads the broker's file.

        Returns:
            pandas.DataFrame: Every row of the file.
        """
        return pandas.read_csv(io.StringIO(MASTER_FILE), dtype=str)


class InMemoryInstrumentDatabase:
    """An in-memory SQLite database arranged to answer the PostgreSQL queries `BrokerInstruments` sends.

    Attributes:
        engine (sqlalchemy.engine.Engine): The engine to hand to the ingester.
        connection (sqlite3.Connection | None): The one SQLite connection behind the engine, once it is open.
    """

    def __init__(self):
        """Builds the engine, the attached schemas, the instrument table and two earlier snapshots.

        Returns:
            None: This method returns nothing.
        """
        sqlite3.register_adapter(datetime.date, self.adapt_date)
        sqlite3.register_converter('DATE', self.convert_date)
        self.connection = None
        self.engine = sqlalchemy.create_engine(
            'sqlite://',
            poolclass=sqlalchemy.pool.StaticPool,
            connect_args={
                'detect_types': sqlite3.PARSE_DECLTYPES,
            },
        )
        sqlalchemy.event.listen(self.engine, 'connect', self.prepare_connection)
        with self.engine.begin() as connection:
            connection.execute(sqlalchemy.text('create table information_schema.columns (table_schema text, table_name text, column_name text, ordinal_position integer)'))
            position = 1
            for column_name in TABLE_COLUMNS:
                connection.execute(
                    sqlalchemy.text('insert into information_schema.columns values (:schema, :table, :column, :position)'),
                    {
                        'schema': 'demo',
                        'table': 'instruments',
                        'column': column_name,
                        'position': position,
                    },
                )
                position = position + 1
            connection.execute(sqlalchemy.text('create table demo.instruments (exchange text, trading_symbol text, series text, lot_size text, download_date DATE)'))
            self.insert_snapshot(connection, datetime.date(2026, 9, 28), 4)
            self.insert_snapshot(connection, datetime.date(2026, 9, 29), 5)

    def adapt_date(self, value):
        """Writes a date as ISO text, the way SQLite stores it.

        Args:
            value (datetime.date): The date to store.

        Returns:
            str: The date as `YYYY-MM-DD`.
        """
        return value.isoformat()

    def convert_date(self, value):
        """Reads a stored date back as a `datetime.date`, as PostgreSQL returns it.

        Args:
            value (bytes): The stored text.

        Returns:
            datetime.date: The date.
        """
        return datetime.date.fromisoformat(value.decode('ascii'))

    def prepare_connection(self, connection, connection_record):
        """Attaches the two schemas and adds the `to_regclass` function when SQLite opens its connection.

        Args:
            connection (sqlite3.Connection): The new SQLite connection.
            connection_record (Any): SQLAlchemy's record of the connection, unused here.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection
        connection.execute("attach database ':memory:' as demo")
        connection.execute("attach database ':memory:' as information_schema")
        connection.create_function('to_regclass', 1, self.to_regclass)

    def to_regclass(self, qualified_name):
        """Stands in for PostgreSQL's `to_regclass`, naming the table when it exists.

        Args:
            qualified_name (str): The table name with its schema, such as `demo.instruments`.

        Returns:
            str | None: The name when the table exists, otherwise None.
        """
        schema, table = qualified_name.split('.')
        cursor = self.connection.execute(f'select count(*) from {schema}.sqlite_master where type = ? and name = ?', ('table', table))
        if cursor.fetchone()[0] == 0:
            return None
        return qualified_name

    def insert_snapshot(self, connection, download_date, row_count):
        """Stores an earlier day's snapshot of made-up rows.

        Args:
            connection (sqlalchemy.engine.Connection): An open connection.
            download_date (datetime.date): The snapshot's date.
            row_count (int): How many rows to store.

        Returns:
            None: This method returns nothing.
        """
        for index in range(row_count):
            connection.execute(
                sqlalchemy.text('insert into demo.instruments values (:exchange, :symbol, :series, :lot_size, :download_date)'),
                {
                    'exchange': 'NSE',
                    'symbol': f'SYMBOL{index}',
                    'series': 'EQ',
                    'lot_size': '1',
                    'download_date': download_date,
                },
            )


class StoringDailySnapshotsExample:
    """Ingests one date three ways and checks its row count.

    Attributes:
        instruments (DemoInstruments): The ingester being shown, with its engine replaced.
        download_date (datetime.date): The date being ingested.
    """

    def __init__(self):
        """Builds the ingester and points it at the in-memory database.

        Returns:
            None: This method returns nothing.
        """
        self.instruments = DemoInstruments()
        self.instruments.engine = InMemoryInstrumentDatabase().engine
        self.download_date = datetime.date(2026, 9, 30)

    def run(self):
        """Ingests the date, ingests it again, replaces it, and checks the row counts.

        Returns:
            None: This method returns nothing.
        """
        print(f'Columns of {self.instruments.table}: {self.instruments.table_columns()}')
        print(f'Stored for {self.download_date} before: {self.instruments.has_data_for(self.download_date)}')
        stored = self.instruments.ingest(download_date=self.download_date)
        print(f'First ingest returned {stored}')
        print(f'Stored for {self.download_date} after: {self.instruments.has_data_for(self.download_date)}')
        stored = self.instruments.ingest(download_date=self.download_date)
        print(f'Second ingest returned {stored}')
        stored = self.instruments.ingest(download_date=self.download_date, bootstrap=True)
        print(f'Bootstrap ingest returned {stored}')
        print()
        report = self.instruments.check_row_count_deviation(self.download_date)
        print(f'Alarm at 10%: {report["alarm"]}')
        report = self.instruments.check_row_count_deviation(self.download_date, threshold=0.5)
        print(f'Alarm at 50%: {report["alarm"]}')
        report = self.instruments.check_row_count_deviation(datetime.date(2026, 10, 1))
        print(f'Alarm for a date with no rows: {report["alarm"]}')


if __name__ == '__main__':
    StoringDailySnapshotsExample().run()
