"""Shows what `FactorBuilder` does with evidence it cannot confirm by itself: an unlisted step, a listed event with no step, a raw gap, and a ticker that does not fit.

Only a step that matches a split Yahoo lists is confirmed automatically. This program calls the builder's steps one at a time to show the rest:

- `derive` on a demerger-shaped history: q steps from 0.923 to 1 on 2023-07-20 with no listed event, and the raw close falls by about the same amount, so the step is stored as a provisional `unclassified` row that notes the raw price fell alike, for a person to confirm. A split Yahoo lists on 2023-07-10, well inside the history but with no step in q, is `rejected`, because the stored prices already move with Yahoo's across it.
- `raw_gaps` on INDIAGLYCO's raw closes, which halve overnight on 2026-09-02 with nothing derived nearby: the move becomes a provisional `raw_gap` row carrying the evidence gathered, including that the series changed token that day and the factor Dhan's re-adjusted history implies, which `dhan_factor` reads.
- `store` writing those rows, except for a date a person has already decided by hand, and `record_fetch` noting a failed fetch.
- `build_one` for a BSE share whose every ticker form is a stub, which is recorded as `empty`, and for one whose newest q is 0.5 rather than 1, which means the ticker is not this instrument and is recorded as `mismatch`.

The constructor opens PostgreSQL through `get_postgres`, which the example runner points at a closed port, so the program replaces `get_postgres` in the factors module with a stand-in that returns an in-memory connection answering the builder's queries with canned rows and recording what is written. The Yahoo client is passed in as a stand-in, so the network is never touched.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/utilities/unified/factors/FactorBuilder/example_2_steps_yahoo_does_not_explain.py
"""

import datetime

from stock_brokers.instruments.historical.utilities.unified import factors
from stock_brokers.instruments.historical.utilities.unified.factors import (
    FactorBuilder,
)

DEMERGER_DATE = datetime.date(2023, 7, 20)
GAP_DATE = datetime.date(2026, 9, 2)


class StandInYahooClient:
    """A stand-in for `YahooClient` that answers a stub for every BSE form and a mismatched history for one NSE ticker.

    Attributes:
        tickers (list): Every ticker asked for.
    """

    def __init__(self):
        """Starts with no tickers asked for.

        Returns:
            None: This method returns nothing.
        """
        self.tickers = []

    def history(self, ticker):
        """Answers Yahoo's closes and listed events for a ticker.

        Args:
            ticker (str): The Yahoo ticker.

        Returns:
            tuple: (closes by date, events by date).
        """
        self.tickers.append(ticker)
        closes = {}
        if ticker == 'WRONGCO.NS':
            day = datetime.date(2026, 9, 1)
            for position in range(12):
                closes[day + datetime.timedelta(days=position)] = 50.0
        if ticker == 'STUBCO.BO':
            closes[datetime.date(2026, 9, 1)] = 100.0
        return closes, {}


class StandInCursor:
    """A stand-in for a psycopg2 cursor that hands every statement to its connection.

    Attributes:
        connection (StandInConnection): The connection that answers the statements.
        result (list): The rows the last statement produced.
        rowcount (int): How many rows the last statement changed.
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
        self.rowcount = 0

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
            parameters (tuple | dict): The statement's parameters.

        Returns:
            None: This method returns nothing.
        """
        self.result, self.rowcount = self.connection.answer(statement, parameters)

    def fetchone(self):
        """The first row the last statement produced.

        Returns:
            tuple | None: The row, or None when there was none.
        """
        if not self.result:
            return None
        return self.result[0]

    def fetchall(self):
        """Every row the last statement produced.

        Returns:
            list: The rows.
        """
        return self.result


class StandInConnection:
    """A stand-in for a psycopg2 connection with raw closes for two instruments and one Dhan bar.

    Attributes:
        raw (dict): Instrument id to its raw (date, close, source id) rows.
        factors_written (list): Every adjustment factor row inserted.
        fetches_written (list): Every Yahoo fetch state row written.
    """

    def __init__(self):
        """Fills in twelve days of raw closes for two instruments.

        Returns:
            None: This method returns nothing.
        """
        self.raw = {}
        self.factors_written = []
        self.fetches_written = []
        instrument_ids = [
            'STUBCO-BSE',
            'WRONGCO-NSE',
        ]
        for instrument_id in instrument_ids:
            rows = []
            day = datetime.date(2026, 9, 1)
            for position in range(12):
                row = (
                    day + datetime.timedelta(days=position),
                    100.0,
                    601,
                )
                rows.append(row)
            self.raw[instrument_id] = rows

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
            parameters (tuple | dict): The statement's parameters.

        Returns:
            tuple: (rows, rows changed).
        """
        if 'close, source_id' in statement:
            return self.raw[parameters[0]], 0
        if 'join dhan.price_history' in statement:
            row = (
                242.5,
            )
            return [row], 0
        if "source = 'manual'" in statement and 'select ex_date' in statement:
            row = (
                datetime.date(2023, 7, 10),
            )
            return [row], 0
        if 'delete from' in statement:
            return [], 2
        if 'insert into unified.adjustment_factors' in statement:
            self.factors_written.append(parameters)
            return [], 1
        if 'insert into unified.yahoo_fetch_state' in statement:
            self.fetches_written.append(parameters)
            return [], 1
        raise ValueError(f'The stand-in does not know this statement: {statement[:60]}')

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


class StepsYahooDoesNotExplainExample:
    """Calls the builder's steps one at a time and prints what each decides.

    Attributes:
        connection (StandInConnection): The in-memory connection.
        yahoo (StandInYahooClient): The stand-in Yahoo client.
        builder (FactorBuilder): The builder being shown.
    """

    def __init__(self):
        """Installs the stand-in connection and builds the builder.

        Returns:
            None: This method returns nothing.
        """
        self.connection = StandInConnection()
        factors.get_postgres = StandInPostgres(self.connection).get_postgres
        self.yahoo = StandInYahooClient()
        self.builder = FactorBuilder(self.yahoo)

    def weekdays(self, first_day, count):
        """Lists a number of weekdays from a date.

        Args:
            first_day (datetime.date): The first date.
            count (int): How many weekdays to list.

        Returns:
            list: The dates.
        """
        days = []
        day = first_day
        while len(days) < count:
            if day.weekday() < 5:
                days.append(day)
            day += datetime.timedelta(days=1)
        return days

    def describe(self, row):
        """Prints one factor row on one line, with its evidence below.

        Args:
            row (dict): The row.

        Returns:
            None: This method returns nothing.
        """
        print(f"  {row['ex_date']} {row['kind']} {row['status']} from {row['source']}, price factor {round(row['price_factor'], 4)}")
        print(f"    evidence {row['evidence']}")

    def derive_demerger(self):
        """Derives rows for a demerger-shaped history with one listed event that shows no step.

        Returns:
            list: The derived rows.
        """
        days = self.weekdays(datetime.date(2023, 6, 26), 30)
        raw_closes = []
        ratios = []
        for day in days:
            if day < DEMERGER_DATE:
                raw_closes.append(2600.0)
                ratios.append(0.923)
            else:
                raw_closes.append(2400.0)
                ratios.append(1.0)
        events = {
            datetime.date(2023, 7, 10): 2.0,
        }
        return self.builder.derive('DEMERGE-NSE', 'DEMERGE.NS', days, raw_closes, ratios, events)

    def find_raw_gap(self):
        """Looks for overnight raw moves nothing explains in INDIAGLYCO's closes.

        Returns:
            list: The raw gap rows.
        """
        days = self.weekdays(datetime.date(2026, 8, 24), 12)
        raw_closes = []
        source_ids = []
        for day in days:
            if day < GAP_DATE:
                raw_closes.append(485.0)
                source_ids.append(701)
            else:
                raw_closes.append(242.5)
                source_ids.append(702)
        return self.builder.raw_gaps('INDIAGLYCO-NSE', 'nse', days, raw_closes, source_ids, [])

    def run(self):
        """Walks through each step and prints what it decided and wrote.

        Returns:
            None: This method returns nothing.
        """
        derived = self.derive_demerger()
        print('derive, for a demerger-shaped history:')
        for row in derived:
            self.describe(row)
        gaps = self.find_raw_gap()
        print('raw_gaps, for INDIAGLYCO:')
        for row in gaps:
            self.describe(row)
        dhan = self.builder.dhan_factor('INDIAGLYCO-NSE', 'nse', datetime.date(2026, 9, 1), 485.0)
        print(f'dhan_factor on 2026-09-01: {dhan}')
        self.builder.store('DEMERGE-NSE', derived)
        print(f'Rows stored: {len(self.connection.factors_written)}, the manually decided 2023-07-10 left alone')
        self.builder.record_fetch('INDIAGLYCO-NSE', None, None, 'error', 'Yahoo answered 404', None, None, None)
        self.builder.build_one('STUBCO-BSE', 'bse', 'STUBCO', '599999', False)
        self.builder.build_one('WRONGCO-NSE', 'nse', 'WRONGCO', None)
        print(f'Yahoo tickers asked for: {self.yahoo.tickers}')
        for fetch in self.connection.fetches_written:
            print(f'Fetch state for {fetch[0]}: ticker {fetch[1]}, status {fetch[3]}, error {fetch[4]}')
        self.builder.count('checked_by_hand')
        print(f'Counts: {self.builder.counts}')


if __name__ == '__main__':
    StepsYahooDoesNotExplainExample().run()
