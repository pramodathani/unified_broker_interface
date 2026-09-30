"""Seeds a small broker's work queue, claims one series and downloads one window of daily bars into it.

`BrokerCandles` is the shared machinery behind every broker's candle download. A broker module only says which intervals it serves, how far one request may reach, how to fetch one window and how to read the answer; the base class decides the order of the work, which window to ask for next, and how to store the bars and move the series' watermark.

This program writes that small broker module itself: `ExampleBrokerCandles` fetches from a stand-in history API that answers with a canned Kite-shaped payload, so no broker is contacted. The base class's constructor opens a PostgreSQL connection through `get_postgres`, and the example runner points PostgreSQL at a closed port, so before building the downloader the program replaces `get_postgres` in the base module with a stand-in that hands out an in-memory connection. That stand-in answers the handful of statements the base class sends, the instrument list, the progress table's row count, the next series to claim and the summary counts, and it records every insert and update so the program can show what would have been written.

What to notice in the output: cash sorts ahead of futures and futures ahead of options, day bars ahead of five-minute bars; seeding a second time adds nothing, because existing series are left as they are; the claimed series has already walked back to 2026-03-01, so the next window ends the day before and spans the 365 days a daily request may cover; and the day bars stamped at midnight India time come back as timezone-aware times. The broker receives two requests, because the program first calls `fetch_candles` and `parse_response` by hand to show them, and `visit` then fetches the same window again to store it. The expiry dates in the priority table are chosen far in the past and far in the future, so whether a contract counts as expired does not depend on the day the program runs.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/BrokerCandles/example_1_one_window_of_daily_bars.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.historical import base

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class StandInCursor:
    """A stand-in for a psycopg2 cursor that hands every statement to its connection.

    Attributes:
        connection (StandInConnection): The connection that answers the statements.
        result (list): The rows the last statement produced.
    """

    def __init__(self, connection):
        """Builds a cursor over a stand-in connection.

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

    def mogrify(self, template, arguments):
        """Stages one row of a multi-row insert, as `execute_values` asks a cursor to.

        Args:
            template (bytes): The row template.
            arguments (tuple): The row's values.

        Returns:
            bytes: A placeholder for the rendered row.
        """
        self.connection.staged_rows.append(arguments)
        return b'(...)'

    def execute(self, statement, parameters=None):
        """Runs one statement against the stand-in connection.

        Args:
            statement (str | bytes): The SQL text.
            parameters (tuple | None): The statement's parameters.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(statement, bytes):
            statement = statement.decode()
        self.result = self.connection.answer(statement, parameters)

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
    """A stand-in for a psycopg2 connection holding a tiny progress table in memory.

    Attributes:
        encoding (str): The client encoding, which `execute_values` reads.
        OUTCOMES (tuple): The outcome names a progress update may write literally.
        instruments (list): The rows the instrument master query returns.
        pending_series (list): The series `claim` hands out, in order.
        progress (list): The (token, interval) pairs registered in the progress table.
        staged_rows (list): Rows staged by `mogrify` for the next insert.
        stored_bars (list): Every bar row written to the price table.
        outcomes (list): One (token, interval, outcome) triple per progress update.
        closed (bool): Whether `close` has been called.
    """

    encoding = 'UTF8'
    OUTCOMES = (
        'stored',
        'empty',
        'backfilled',
        'throttled',
        'failed',
        'retired',
    )

    def __init__(self, instruments, pending_series):
        """Builds the connection with the rows it will answer with.

        Args:
            instruments (list): The rows the instrument master query returns.
            pending_series (list): The series `claim` hands out, in order.

        Returns:
            None: This method returns nothing.
        """
        self.instruments = instruments
        self.pending_series = pending_series
        self.progress = []
        self.staged_rows = []
        self.stored_bars = []
        self.outcomes = []
        self.closed = False

    def cursor(self):
        """Opens a cursor.

        Returns:
            StandInCursor: A new cursor.
        """
        return StandInCursor(self)

    def commit(self):
        """Accepts a commit, which the stand-in has nothing to do for.

        Returns:
            None: This method returns nothing.
        """
        return None

    def rollback(self):
        """Accepts a rollback, which the stand-in has nothing to do for.

        Returns:
            None: This method returns nothing.
        """
        return None

    def close(self):
        """Marks the connection closed.

        Returns:
            None: This method returns nothing.
        """
        self.closed = True

    def answer(self, statement, parameters):
        """Produces the rows one statement would return, and records what it would write.

        Args:
            statement (str): The SQL text.
            parameters (tuple | None): The statement's parameters.

        Returns:
            list: The rows the statement returns.
        """
        if 'select distinct on' in statement:
            return list(self.instruments)
        if 'select count(*),' in statement:
            return [
                self.summary_row(),
            ]
        if 'select count(*) from' in statement:
            return [
                (
                    len(self.progress),
                ),
            ]
        if 'select instrument_token' in statement:
            if not self.pending_series:
                return []
            return [
                self.pending_series.pop(0),
            ]
        if 'insert into' in statement:
            rows = self.staged_rows
            self.staged_rows = []
            if 'price_history_progress' in statement:
                for row in rows:
                    key = (
                        row[0],
                        row[1],
                    )
                    if key not in self.progress:
                        self.progress.append(key)
            else:
                self.stored_bars.extend(rows)
            return []
        if 'update' in statement:
            self.outcomes.append(self.outcome_of(statement, parameters))
        return []

    def summary_row(self):
        """Counts the progress table the way the summary query does.

        Returns:
            tuple: The series, retired series, series with bars, bars and stuck series.
        """
        retired = 0
        series_with_bars = []
        for token, interval, outcome in self.outcomes:
            if outcome == 'retired':
                retired += 1
            if outcome == 'stored' and (token, interval) not in series_with_bars:
                series_with_bars.append((token, interval))
        return (
            len(self.progress),
            retired,
            len(series_with_bars),
            len(self.stored_bars),
            0,
        )

    def outcome_of(self, statement, parameters):
        """Reads which outcome a progress update records.

        Args:
            statement (str): The update's SQL text.
            parameters (tuple): The update's parameters, ending with the token and interval.

        Returns:
            tuple: The (token, interval, outcome) the update records.
        """
        token = parameters[-2]
        interval = parameters[-1]
        outcome = 'unknown'
        if 'last_outcome = %s' in statement:
            outcome = parameters[0]
        for name in self.OUTCOMES:
            if f"last_outcome = '{name}'" in statement:
                outcome = name
        return (
            token,
            interval,
            outcome,
        )


class StandInPostgres:
    """Hands the downloader a stand-in connection in place of a real PostgreSQL one.

    Attributes:
        connection (StandInConnection): The connection handed out.
    """

    def __init__(self, connection):
        """Holds the connection to hand out.

        Args:
            connection (StandInConnection): The connection handed out.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection

    def get_postgres(self):
        """Returns the stand-in connection, in the place of `utilities.configurations.get_postgres`.

        Returns:
            StandInConnection: The connection.
        """
        return self.connection


class StandInHistoryAPI:
    """A stand-in for a broker's history endpoint that answers with a canned Kite-shaped payload.

    Attributes:
        requests (list): Every request received, as (token, interval, start, end) tuples.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def historical_data(self, token, interval, start_date, end_date):
        """Answers a history request with three daily candles.

        Args:
            token (str): The broker's instrument token.
            interval (str): The broker's interval code.
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            dict: The decoded response, with a `candles` list.
        """
        self.requests.append(
            (
                token,
                interval,
                start_date,
                end_date,
            ),
        )
        return {
            'candles': [
                [
                    '2026-02-25T00:00:00+0530',
                    1391.0,
                    1402.5,
                    1385.2,
                    1398.4,
                    6123450,
                ],
                [
                    '2026-02-26T00:00:00+0530',
                    1398.4,
                    1410.0,
                    1392.1,
                    1405.9,
                    5870012,
                ],
                [
                    '2026-02-27T00:00:00+0530',
                    1405.9,
                    1406.5,
                    1380.0,
                    1384.3,
                    7211904,
                ],
            ],
        }


class ExampleBrokerCandles(base.BrokerCandles):
    """A made-up broker's candle download, reading Kite-shaped candles from a history API.

    Attributes:
        history_api (StandInHistoryAPI): Where windows of candles are fetched from.
    """

    BROKER_NAME = 'example_broker'
    INTERVALS = {
        'day': 'day',
        '5minute': '5minute',
    }
    MAXIMUM_WINDOW_DAYS = {
        'day': 365,
        '5minute': 60,
    }
    REQUESTS_PER_SECOND = 50.0
    EARLIEST_AVAILABLE_DATE = datetime.date(2015, 1, 1)

    def __init__(self, history_api):
        """Builds the downloader around a history API.

        Args:
            history_api (StandInHistoryAPI): Where windows of candles are fetched from.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.history_api = history_api

    def fetch_candles(self, token, interval, start_date, end_date):
        """Fetches one window of candles.

        Args:
            token (str): The broker's instrument token.
            interval (str): The stored interval name.
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            dict: The decoded response.
        """
        return self.history_api.historical_data(token, self.INTERVALS[interval], start_date, end_date)

    def parse_response(self, payload, interval):
        """Turns a Kite-shaped response into bar tuples.

        Args:
            payload (dict): The decoded response.
            interval (str): The stored interval name.

        Returns:
            list: One (time, open, high, low, close, volume, oi) tuple per candle.
        """
        bars = []
        for candle in payload.get('candles', []):
            moment = datetime.datetime.strptime(candle[0], '%Y-%m-%dT%H:%M:%S%z')
            if not base.is_intraday(interval):
                moment = base.daily_bar_time(moment)
            open_interest = None
            if len(candle) > 6:
                open_interest = candle[6]
            bars.append(
                (
                    moment,
                    candle[1],
                    candle[2],
                    candle[3],
                    candle[4],
                    candle[5],
                    open_interest,
                ),
            )
        return bars


class OneWindowOfDailyBarsExample:
    """Seeds the queue, claims a series and stores one window of its daily bars.

    Attributes:
        connection (StandInConnection): The in-memory database.
        history_api (StandInHistoryAPI): The stand-in broker endpoint.
        downloader (ExampleBrokerCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader over the stand-in database and history API.

        Returns:
            None: This method returns nothing.
        """
        instruments = [
            (
                '738561',
                'EQ',
                None,
            ),
            (
                '13368834',
                'FUT',
                '2099-12-31',
            ),
            (
                '13368835',
                'CE',
                '2020-01-30',
            ),
        ]
        pending_series = [
            (
                '738561',
                'day',
                datetime.datetime(2026, 3, 2, tzinfo=INDIA),
                datetime.datetime(2026, 9, 29, tzinfo=INDIA),
                datetime.datetime(2026, 3, 1, tzinfo=INDIA),
                0,
                0,
            ),
        ]
        self.connection = StandInConnection(instruments, pending_series)
        base.get_postgres = StandInPostgres(self.connection).get_postgres
        self.history_api = StandInHistoryAPI()
        self.downloader = ExampleBrokerCandles(self.history_api)

    def run(self):
        """Walks through one window of work and prints each step.

        Returns:
            None: This method returns nothing.
        """
        print(f'Series context for 738561: {ExampleBrokerCandles.series_context("738561")}')
        print('Priority of each series (lower is worked first):')
        for token, instrument_type, expiry in self.downloader.instruments():
            for interval in ExampleBrokerCandles.INTERVALS:
                priority = self.downloader.priority_for(instrument_type, expiry, interval)
                print(f'  {token} {instrument_type} expiry {expiry} {interval}: {priority}')
        print(f'Series added by the first seed: {self.downloader.seed()}')
        print(f'Series added by a second seed: {self.downloader.seed()}')
        series = self.downloader.claim()
        print(f'Claimed: {series[0]} {series[1]}, oldest requested {series[4].date()}')
        start_date, end_date, direction = self.downloader.next_window(series)
        print(f'Next window: {start_date} to {end_date}, walking {direction}')
        payload = self.downloader.fetch_candles(series[0], series[1], start_date, end_date)
        bars = self.downloader.parse_response(payload, series[1])
        print(f'Parsed {len(bars)} bars; the first is {bars[0][0].isoformat()} close {bars[0][4]}')
        stored = self.downloader.visit(series)
        print(f'Bars stored by visit: {stored}')
        for row in self.connection.stored_bars:
            print(f'  wrote {row[0].isoformat()} {row[1]} {row[2]} close {row[6]} volume {row[7]}')
        print(f'Progress updates: {self.connection.outcomes}')
        print(f'Requests sent to the broker: {len(self.history_api.requests)}')
        print(f'Summary: {self.downloader.summary()}')
        self.downloader.close()
        print(f'Connection closed: {self.connection.closed}')


if __name__ == '__main__':
    OneWindowOfDailyBarsExample().run()
