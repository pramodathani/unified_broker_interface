"""Fetches a broker's full raw instrument row for one of its tokens, from the latest snapshot on or before a date.

The mapped tables keep only a token, the symbols, the lot size and the tick size. When a caller needs something else from a broker's own file, `raw_row` reads the whole row from that broker's `instruments` table, using the token column the broker is keyed on, such as Zerodha's `instrument_token`.

`raw_row` reads through pandas, which needs a real SQLAlchemy connection, so this program gives the resolver an in-memory SQLite database instead of a small stand-in. SQLite has no schemas, so a second in-memory database is attached under the name `zerodha` to make the table `zerodha.instruments` exist; it holds two days of Zerodha's row for INFY, with the last price changed between them. Python's default way of passing a date to SQLite is deprecated, so the program registers `datetime.date.isoformat` as the adapter. A tiny stand-in cache only carries the engine, and no PostgreSQL or Redis is reached.

Notice that asking about 2026-09-27 returns that day's row even though a later one exists, that an unknown token gives None, and that a broker outside the mapped ten raises `ValueError` before any query, because the broker name becomes part of the table name.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/resolution/MappingResolver/example_3_a_brokers_raw_row.py
"""

import datetime
import sqlite3

import sqlalchemy

from stock_brokers.instruments.mapping.utilities.resolution import (
    MappingResolver,
)


class EngineOnlyMappingCache:
    """A stand-in for `MappingCache` that only lends its engine, which is all `raw_row` uses.

    Attributes:
        engine (sqlalchemy.engine.Engine): The in-memory SQLite engine.
    """

    def __init__(self, engine):
        """Holds the engine.

        Args:
            engine (sqlalchemy.engine.Engine): The in-memory SQLite engine.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine


class BrokersRawRowExample:
    """Fills an in-memory Zerodha snapshot and reads rows back through the resolver.

    Attributes:
        engine (sqlalchemy.engine.Engine): The in-memory SQLite engine.
        resolver (MappingResolver): The resolver being shown.
    """

    def __init__(self):
        """Builds the in-memory database, fills it and builds the resolver.

        Returns:
            None: This method returns nothing.
        """
        sqlite3.register_adapter(datetime.date, datetime.date.isoformat)
        self.engine = sqlalchemy.create_engine('sqlite://')
        with self.engine.begin() as connection:
            connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS zerodha")
            connection.exec_driver_sql(
                'CREATE TABLE zerodha.instruments ('
                'instrument_token TEXT, exchange_token TEXT, tradingsymbol TEXT, name TEXT, '
                'last_price TEXT, tick_size TEXT, lot_size TEXT, exchange TEXT, download_date TEXT)'
            )
            connection.exec_driver_sql(
                'INSERT INTO zerodha.instruments VALUES '
                "('408065', '1594', 'INFY', 'INFOSYS', '1532.4', '0.1', '1', 'NSE', '2026-09-27'), "
                "('408065', '1594', 'INFY', 'INFOSYS', '1547.9', '0.1', '1', 'NSE', '2026-09-28')"
            )
        self.resolver = MappingResolver(EngineOnlyMappingCache(self.engine))

    def run(self):
        """Prints the row for two dates, the answer for an unknown token and the refusal of an unknown broker.

        Returns:
            None: This method returns nothing.
        """
        row = self.resolver.raw_row('zerodha', 408065, datetime.date(2026, 9, 27))
        print(f'As of 2026-09-27: {row}')
        row = self.resolver.raw_row('zerodha', '408065', datetime.date(2026, 9, 30))
        print(f'As of 2026-09-30: last price {row["last_price"]} from {row["download_date"]}')
        print(f'Unknown token: {self.resolver.raw_row("zerodha", "999999", datetime.date(2026, 9, 30))}')
        try:
            self.resolver.raw_row('upstox', '408065', datetime.date(2026, 9, 30))
        except ValueError as error:
            print(f'ValueError: {error}')


if __name__ == '__main__':
    BrokersRawRowExample().run()
