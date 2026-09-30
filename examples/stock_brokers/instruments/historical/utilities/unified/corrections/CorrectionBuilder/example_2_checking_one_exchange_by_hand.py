"""Calls each step of `CorrectionBuilder` by hand for a share listed on NSE only, whose split went ex two days ago.

With no BSE listing there is no cross-exchange ratio, so the evidence has to come from Flattrade's raw 15 minute bars: `intraday_last_closes` reads the last intraday close of each day, and `intraday` compares it with the daily close. Here the daily series was served at half its price before a 1:2 split of 2026-09-28, so the ratio of last intraday close to daily close is 2 before the split and 1 from it. The step snaps to 2/1, but it has been seen for only two days on the newer side, fewer than the three the builder waits for, so the row stays provisional, as PGIL's did in the module's documentation. Yahoo lists the split on the same day while the served series does not move across it, which is what a pre-adjusted series looks like, so `yahoo_events` proposes a provisional row too, and `merge` folds it into the intraday row as evidence.

The program also shows the smaller helpers: `own_level` takes the median of a series' own closes on one side of a date; `cross_exchange` gives nothing for a pair whose ratio never settles near 1, which it counts as not anchored; `rows` builds one row per series with bars before the ex-date; `merge` leaves a row provisional when two methods disagree on the multiplier by more than 2%; and `store` writes the rows. The builder opens PostgreSQL through `get_postgres`, which the example runner points at a closed port, so the program replaces `get_postgres` in the corrections module with a stand-in returning an in-memory connection that answers each query with canned rows and records what is written. Because every stored row is provisional, the confirmed corrections do not change and no rebuild is flagged.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/corrections/CorrectionBuilder/example_2_checking_one_exchange_by_hand.py
"""

import datetime

from stock_brokers.instruments.historical.utilities.unified import corrections
from stock_brokers.instruments.historical.utilities.unified.corrections import (
    CorrectionBuilder,
)

SPLIT_DATE = datetime.date(2026, 9, 28)
SERIES = 'NSE|40001|SOLOCO-EQ'


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
    """A stand-in for a psycopg2 connection holding SOLOCO's served daily closes and its last intraday closes.

    Attributes:
        daily (list): (date, close, broker series) rows as served.
        last_intraday (list): (date, last 15 minute close) rows.
        corrections_written (list): Every correction row inserted.
        follow_ups (list): The first words of every other statement that changes data.
    """

    def __init__(self):
        """Fills in the closes for the weekdays of September 2026.

        Returns:
            None: This method returns nothing.
        """
        self.daily = []
        self.last_intraday = []
        self.corrections_written = []
        self.follow_ups = []
        day = datetime.date(2026, 9, 1)
        while day <= datetime.date(2026, 9, 29):
            if day.weekday() < 5:
                raw_close = 500.0
                if day < SPLIT_DATE:
                    raw_close = 1000.0
                self.daily.append(self.row(day, 500.0, SERIES))
                self.last_intraday.append(self.row(day, raw_close))
            day += datetime.timedelta(days=1)

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
                self.row('SOLOCO-NSE', 'nse', 'nse_equities', 'SOLOCO'),
            ]
        if 'b.close, s.broker_series' in statement:
            return self.daily
        if 'select distinct yahoo_event_date' in statement or 'select ex_date, yahoo_event_ratio' in statement:
            return [
                self.row(SPLIT_DATE, 2.0),
            ]
        if 'select distinct on (day) day, close' in statement:
            return self.last_intraday
        if 'select broker_series, ex_date, price_multiplier' in statement:
            return []
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
        """Accepts a rollback.

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


class CheckingOneExchangeExample:
    """Calls the correction builder's steps one at a time for SOLOCO and prints each answer.

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

    def describe(self, label, row):
        """Prints one correction row on one line, with its evidence below.

        Args:
            label (str): What produced the row.
            row (dict): The row.

        Returns:
            None: This method returns nothing.
        """
        print(f"{label}: {row['broker_series']} from {row['ex_date']}, multiplier {row['price_multiplier']} ({row['snapped_ratio']}), by {row['method']}, {row['status']}")
        print(f"  evidence {row['evidence']}")

    def run(self):
        """Walks through each step and prints what it found.

        Returns:
            None: This method returns nothing.
        """
        closes = self.builder.served('SOLOCO-NSE')
        series_names = {
            SERIES,
        }
        last_bars = self.builder.intraday_last_closes(series_names)
        days = sorted(closes)
        print(f'own_level before {SPLIT_DATE}: {self.builder.own_level(closes, days, SPLIT_DATE, True)}, last intraday before it: {last_bars[datetime.date(2026, 9, 25)]}')
        found = self.builder.intraday('SOLOCO-NSE', closes, last_bars)
        for row in found:
            self.describe('intraday', row)
        instrument_ids = [
            'SOLOCO-NSE',
        ]
        print(f'split_events: {self.builder.split_events(instrument_ids)}')
        for row in self.builder.yahoo_events('SOLOCO-NSE', closes):
            self.describe('yahoo_events', row)
            self.builder.merge(found, row)
        for row in found:
            self.describe('after merge', row)
        nse = {}
        bse = {}
        for day in days:
            nse[day] = self.connection.row(100.0, 'NSE|50001|PAIRCO-EQ')
            bse[day] = self.connection.row(140.0, 'BSE|550001|PAIRCO')
        print(f"cross_exchange for a pair that never settles near 1: {self.builder.cross_exchange('PAIRCO-NSE', 'PAIRCO-BSE', nse, bse)}")
        first = self.builder.rows('SOLOCO-NSE', closes, SPLIT_DATE, 2.0, None, 'cross_exchange', 'confirmed', {})
        second = self.builder.rows('SOLOCO-NSE', closes, SPLIT_DATE, 2.5, None, 'intraday', 'confirmed', {})
        disagreeing = list(first)
        self.builder.merge(disagreeing, second[0])
        self.describe('two methods disagreeing, merged', disagreeing[0])
        self.builder.store('SOLOCO-NSE', found)
        self.builder.count('checked_by_hand', 3)
        print(f'Rows written by store: {len(self.connection.corrections_written)}, follow-up statements {self.connection.follow_ups}')
        print(f'Counts: {self.builder.counts}')

if __name__ == '__main__':
    CheckingOneExchangeExample().run()
