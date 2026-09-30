"""Finds that Flattrade served PIDILITIND's NSE daily series already adjusted for its 1:1 bonus, and records the multiplier that undoes it.

Flattrade's NSE daily bars are raw across some corporate actions and already adjusted across others. Before PIDILITIND's bonus of 2025-09-23 its NSE close was served at about 1,519 where the BSE close was about 3,038. `CorrectionBuilder.build` catches this in two ways. The ratio of the BSE close to the NSE close is 2 before the bonus and 1 from it; either series could be the odd one out, so the builder asks what each choice would say both prices did that day, and the listed Yahoo split of 2.0 on 2025-09-23 settles it: correcting NSE leaves both prices halving on the ex-date, as a bonus makes them do. Flattrade's raw 15 minute bars agree: the day's last intraday close is twice the daily close before the bonus, so the intraday check finds the same step, and the two rows are merged into one.

The builder opens PostgreSQL through `get_postgres`, which the example runner points at a closed port, so the program replaces `get_postgres` in the corrections module with a stand-in returning an in-memory connection. That connection answers each query the builder sends with 19 trading days of recorded-looking closes on both exchanges, and records every row written and every follow-up statement. What to notice: one confirmed correction with a multiplier of 2 for the NSE series only, dated 2025-09-23; its evidence names the Yahoo event as what decided it and carries the intraday multiplier; and because the confirmed corrections changed, the instrument's sources are flagged for rebuilding, its rejected Yahoo split events are deleted, and it is made due for a fresh Yahoo fetch.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/corrections/CorrectionBuilder/example_1_a_pre_adjusted_nse_series.py
"""

import datetime

from stock_brokers.instruments.historical.utilities.unified import corrections
from stock_brokers.instruments.historical.utilities.unified.corrections import (
    CorrectionBuilder,
)

BONUS_DATE = datetime.date(2025, 9, 23)
NSE_SERIES = 'NSE|10575|PIDILITIND-EQ'
BSE_SERIES = 'BSE|500331|PIDILITIND'


class StandInCursor:
    """A stand-in for a psycopg2 cursor that hands every statement to its connection.

    Attributes:
        connection (StandInConnection): The connection that answers the statements.
        result (list): The rows the last statement produced.
    """

    def __init__(self, connection):
        """Builds a cursor over the stand-in connection.

        Args:
            connection (StandInConnection): The connection that answers the statements.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection
        self.result = []

    def __enter__(self):
        """Opens the cursor as a context manager.

        Returns:
            StandInCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Closes the cursor, letting any exception carry on.

        Args:
            exception_type (type | None): The class of an exception raised inside the block.
            exception (BaseException | None): The exception raised inside the block.
            traceback (types.TracebackType | None): Where it was raised.

        Returns:
            bool: Always False, so an exception is not swallowed.
        """
        return False

    def execute(self, statement, parameters):
        """Runs one statement against the stand-in connection.

        Args:
            statement (str): The SQL text.
            parameters (tuple): The statement's parameters.

        Returns:
            None: This method returns nothing.
        """
        self.result = self.connection.answer(statement, parameters)

    def fetchall(self):
        """Every row the last statement produced.

        Returns:
            list: The rows.
        """
        return self.result


class StandInConnection:
    """A stand-in for a psycopg2 connection holding PIDILITIND's closes on both exchanges.

    Attributes:
        daily (dict): Instrument id to its (date, close, broker series) rows as served.
        last_intraday (dict): Broker series to its (date, last 15 minute close) rows.
        corrections_written (list): Every correction row inserted.
        follow_ups (list): The first words of every other statement that changes data.
    """

    def __init__(self):
        """Fills in the closes for the weekdays from 2025-09-09 to 2025-10-03.

        Returns:
            None: This method returns nothing.
        """
        self.daily = {
            'PIDILITIND-NSE': [],
            'PIDILITIND-BSE': [],
        }
        self.last_intraday = {
            NSE_SERIES: [],
            BSE_SERIES: [],
        }
        self.corrections_written = []
        self.follow_ups = []
        day = datetime.date(2025, 9, 9)
        position = 0
        while day <= datetime.date(2025, 10, 3):
            if day.weekday() < 5:
                self.add_day(day, position)
                position += 1
            day += datetime.timedelta(days=1)

    def add_day(self, day, position):
        """Adds one trading day's closes.

        Args:
            day (datetime.date): The date.
            position (int): How many trading days came before it, which varies the prices a little.

        Returns:
            None: This method returns nothing.
        """
        raw_close = 1519.0 + (position % 3) * 4.0
        if day < BONUS_DATE:
            raw_close = raw_close * 2
        adjusted_close = 1519.0 + (position % 3) * 4.0
        self.daily['PIDILITIND-BSE'].append(self.row(day, raw_close, BSE_SERIES))
        self.daily['PIDILITIND-NSE'].append(self.row(day, adjusted_close, NSE_SERIES))
        self.last_intraday[BSE_SERIES].append(self.row(day, raw_close))
        self.last_intraday[NSE_SERIES].append(self.row(day, raw_close - 1.6))

    def row(self, *columns):
        """Builds one result row.

        Args:
            *columns (object): The row's columns, in order.

        Returns:
            tuple: The row.
        """
        return columns

    def cursor(self):
        """Opens a stand-in cursor.

        Returns:
            StandInCursor: The cursor.
        """
        return StandInCursor(self)

    def answer(self, statement, parameters):
        """Answers one of the builder's statements.

        Args:
            statement (str): The SQL text.
            parameters (tuple): The statement's parameters.

        Returns:
            list: The rows.
        """
        if 'select distinct m.instrument_id::text' in statement:
            return [
                (
                    'PIDILITIND-BSE',
                    'bse',
                    'bse_equities',
                    'PIDILITIND',
                ),
                (
                    'PIDILITIND-NSE',
                    'nse',
                    'nse_equities',
                    'PIDILITIND',
                ),
            ]
        if 'b.close, s.broker_series' in statement:
            return self.daily[parameters[1]]
        if 'select distinct yahoo_event_date' in statement:
            return [
                (
                    BONUS_DATE,
                    2.0,
                ),
            ]
        if 'select distinct on (day) day, close' in statement:
            rows = []
            for series in parameters[0]:
                rows.extend(self.last_intraday[series])
            return rows
        if 'select ex_date, yahoo_event_ratio' in statement:
            return []
        if 'select broker_series, ex_date, price_multiplier' in statement:
            rows = []
            for written in self.corrections_written:
                if written[4] == parameters[0] and written[7] == 'confirmed':
                    rows.append(self.row(written[1], written[3], written[5]))
            return rows
        if 'insert into unified.price_history_corrections' in statement:
            self.corrections_written.append(parameters)
            return []
        self.follow_ups.append(' '.join(statement.split()[:3]))
        return []

    def commit(self):
        """Accepts a commit.

        Returns:
            None: This method returns nothing.
        """

    def rollback(self):
        """Ends the read transaction the builder holds while reading served prices.

        Returns:
            None: This method returns nothing.
        """


class StandInPostgres:
    """Hands out the stand-in connection in the place of `get_postgres`.

    Attributes:
        connection (StandInConnection): The connection handed out.
    """

    def __init__(self, connection):
        """Remembers the connection to hand out.

        Args:
            connection (StandInConnection): The connection handed out.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection

    def get_postgres(self):
        """Returns the stand-in connection.

        Returns:
            StandInConnection: The connection.
        """
        return self.connection


class PreAdjustedNseSeriesExample:
    """Runs the correction build for the PIDILITIND pair and prints what it stored.

    Attributes:
        connection (StandInConnection): The in-memory connection.
        builder (CorrectionBuilder): The builder being shown.
    """

    def __init__(self):
        """Installs the stand-in connection and builds the builder.

        Returns:
            None: This method returns nothing.
        """
        self.connection = StandInConnection()
        corrections.get_postgres = StandInPostgres(self.connection).get_postgres
        self.builder = CorrectionBuilder()

    def run(self):
        """Prints what the build reads, then builds and prints what it wrote.

        Returns:
            None: This method returns nothing.
        """
        for instrument_id, exchange, segment, symbol in self.builder.instruments():
            served = self.builder.served(instrument_id)
            before = served[datetime.date(2025, 9, 22)][0]
            after = served[BONUS_DATE][0]
            print(f'{symbol} on {exchange}: {len(served)} served closes, {before} on 2025-09-22, {after} on {BONUS_DATE}')
        counts = self.builder.build()
        print(f'Build summary: {counts}')
        for row in self.connection.corrections_written:
            print(f'Stored: {row[1]} from {row[3]}, multiplier {row[5]} ({row[8]}), by {row[6]}, {row[7]}')
            print(f'  evidence {row[10]}')
        print(f'Follow-up statements: {self.connection.follow_ups}')


if __name__ == '__main__':
    PreAdjustedNseSeriesExample().run()
