"""Finds that Flattrade served JBCHEPHARM's NSE daily series already adjusted for its 2023 split when neither Yahoo nor intraday bars say so, because only one exchange's price stepped.

JB Chemicals split each share into two, effective 2023-09-18. Flattrade's BSE daily closes are raw and halve that day, from about 2,955 to about 1,483, while its NSE daily closes stay near 1,480 throughout, because Flattrade served them already adjusted. The ratio of the BSE close to the NSE close is 2 before the split and 1 from it, so one of the two series is at the wrong scale, and the prices alone allow two readings: correcting NSE by 2 says both prices halved, and correcting BSE by a half says neither moved. Yahoo lists no split for it and Flattrade's intraday history does not reach back to 2023, so `CorrectionBuilder.build` decides with `one_series_stepped`: a broker adjusting for a split divides the older prices, so the series to correct is the one that did not move, and its multiplier must be above 1.

The builder opens PostgreSQL through `get_postgres`, which the example runner points at a closed port, so the program replaces `get_postgres` in the corrections module with a stand-in returning an in-memory connection, which answers each query with 20 trading days of recorded-looking closes on both exchanges and records every row written. What to notice: one confirmed correction with a multiplier of 2 for the NSE series only, dated 2023-09-18, whose evidence says it was decided because one series stepped alone, with NSE's own move near 1 and BSE's near a half.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/corrections/CorrectionBuilder/example_3_only_one_exchange_stepped.py
"""

import datetime

from stock_brokers.instruments.historical.utilities.unified import corrections
from stock_brokers.instruments.historical.utilities.unified.corrections import (
    CorrectionBuilder,
)

SPLIT_DATE = datetime.date(2023, 9, 18)
LAST_DAY_BEFORE = datetime.date(2023, 9, 15)
NSE_SERIES = 'NSE|1726|JBCHEPHARM-EQ'
BSE_SERIES = 'BSE|506943|JBCHEPHARM'


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
    """A stand-in for a psycopg2 connection holding JBCHEPHARM's closes on both exchanges.

    Attributes:
        daily (dict): Instrument id to its (date, close, broker series) rows as served.
        last_intraday (dict): Broker series to its (date, last 15 minute close) rows.
        corrections_written (list): Every correction row inserted.
        follow_ups (list): The first words of every other statement that changes data.
    """

    def __init__(self):
        """Fills in the closes for the weekdays from 2023-09-04 to 2023-09-29.

        Returns:
            None: This method returns nothing.
        """
        self.daily = {
            'JBCHEPHARM-NSE': [],
            'JBCHEPHARM-BSE': [],
        }
        self.last_intraday = {
            NSE_SERIES: [],
            BSE_SERIES: [],
        }
        self.corrections_written = []
        self.follow_ups = []
        day = datetime.date(2023, 9, 4)
        position = 0
        while day <= datetime.date(2023, 9, 29):
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
        raw_close = 1478.0 + (position % 3) * 4.0
        if day < SPLIT_DATE:
            raw_close = raw_close * 2
        adjusted_close = 1478.0 + (position % 3) * 4.0
        self.daily['JBCHEPHARM-BSE'].append(self.row(day, raw_close, BSE_SERIES))
        self.daily['JBCHEPHARM-NSE'].append(self.row(day, adjusted_close, NSE_SERIES))

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
                    'JBCHEPHARM-BSE',
                    'bse',
                    'bse_equities',
                    'JBCHEPHARM',
                ),
                (
                    'JBCHEPHARM-NSE',
                    'nse',
                    'nse_equities',
                    'JBCHEPHARM',
                ),
            ]
        if 'b.close, s.broker_series' in statement:
            return self.daily[parameters[1]]
        if 'select distinct yahoo_event_date' in statement:
            return []
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


class OnlyOneExchangeSteppedExample:
    """Runs the correction build for the JBCHEPHARM pair and prints what it stored.

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
            before = served[LAST_DAY_BEFORE][0]
            after = served[SPLIT_DATE][0]
            print(f'{symbol} on {exchange}: {len(served)} served closes, {before} on {LAST_DAY_BEFORE}, {after} on {SPLIT_DATE}')
        counts = self.builder.build()
        print(f'Build summary: {counts}')
        for row in self.connection.corrections_written:
            print(f'Stored: {row[1]} from {row[3]}, multiplier {row[5]} ({row[8]}), by {row[6]}, {row[7]}')
            print(f'  evidence {row[10]}')
        print(f'Follow-up statements: {self.connection.follow_ups}')


if __name__ == '__main__':
    OnlyOneExchangeSteppedExample().run()
