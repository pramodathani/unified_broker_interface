"""Works a queue of seven series until it is drained, showing how the base class reacts to each kind of answer a broker gives.

`run` claims one series at a time, asks `visit` to fetch and store its next window, and stops when nothing is due, when it is asked to stop, or when the broker refuses the session outright. What `visit` records against a series depends on what happened: bars are stored, an empty window counts towards finishing the backward walk, an unknown instrument is retired, a throttle is noted without being held against the series, and any other error pushes the series back with a growing delay.

The broker here is made up. `ExampleBrokerCandles` fetches from a stand-in history API that answers each token from a script, either with canned Kite-shaped candles or with the error message a real broker sends, and its `fetch_candles` turns those messages into the `CandleError` subclasses the base class understands. The base class's constructor would open a PostgreSQL connection, and the example runner points PostgreSQL at a closed port, so the program replaces `get_postgres` in the base module with a stand-in that hands out an in-memory connection. That connection gives out the queued series in order and records the outcome each progress update writes. The project's configuration module sets up logging to standard error when it is imported, so the program sets it up again, with `force=True`, to write to standard output, and the base class's own messages then appear in order with the program's.

What to notice in the output: the empty window finishes the backfill because it is the third in a row; the series whose backward walk is done and whose last bar is in 2099 is put aside as up to date, whichever day the program runs; the series with no bars anywhere is retired without a request being sent; and the throttled series is left claimable. The throttle is scripted last on purpose, because the base class then holds the next request back five seconds, and the queue is empty by then. A final call with a stop event that is already set shows `run` returning at once.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/BrokerCandles/example_2_run_until_the_queue_is_drained.py
"""

import datetime
import logging
import sys
import threading
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


class StandInBrokerError(Exception):
    """An error a stand-in broker answers with, carrying the broker's own message."""


class StandInHistoryAPI:
    """A stand-in for a broker's history endpoint that answers each token from a script.

    Attributes:
        answers (dict): Token to the payload to return, or to the error message to raise.
        requests (list): The tokens requested, in order.
    """

    def __init__(self, answers):
        """Builds the stand-in with its scripted answers.

        Args:
            answers (dict): Token to the payload to return, or to the error message to raise.

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers
        self.requests = []

    def historical_data(self, token, interval, start_date, end_date):
        """Answers a history request from the script.

        Args:
            token (str): The broker's instrument token.
            interval (str): The broker's interval code.
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            dict: The decoded response, with a `candles` list.

        Raises:
            StandInBrokerError: When the script gives an error message for the token.
        """
        del interval, start_date, end_date
        self.requests.append(token)
        answer = self.answers[token]
        if isinstance(answer, str):
            raise StandInBrokerError(answer)
        return answer


class ExampleBrokerCandles(base.BrokerCandles):
    """A made-up broker's candle download, reading Kite-shaped candles and Kite-style error messages.

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
        """Fetches one window of candles, turning the broker's refusals into candle errors.

        Args:
            token (str): The broker's instrument token.
            interval (str): The stored interval name.
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            dict: The decoded response.

        Raises:
            CandleInstrumentUnknown: When the broker does not know the token.
            CandleThrottled: When the broker asks for fewer requests.
            CandleAuthenticationError: When the broker refuses the session.
            StandInBrokerError: For any other refusal.
        """
        try:
            return self.history_api.historical_data(token, self.INTERVALS[interval], start_date, end_date)
        except StandInBrokerError as error:
            message = str(error)
            if 'invalid token' in message:
                raise base.CandleInstrumentUnknown(message) from error
            if 'Too many requests' in message:
                raise base.CandleThrottled(message) from error
            if 'TokenException' in message:
                raise base.CandleAuthenticationError(message) from error
            raise

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


class RunUntilTheQueueIsDrainedExample:
    """Runs the download over a scripted queue and prints what happened to each series.

    Attributes:
        connection (StandInConnection): The in-memory database.
        history_api (StandInHistoryAPI): The stand-in broker endpoint.
        downloader (ExampleBrokerCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader over a queue of seven series and a scripted broker.

        Returns:
            None: This method returns nothing.
        """
        pending_series = [
            self.series('738561', 'day', datetime.date(2026, 3, 1), datetime.date(2026, 9, 29), 0),
            self.series('500325', 'day', datetime.date(2018, 1, 1), datetime.date(2026, 9, 29), 2),
            self.series('13368834', '5minute', None, None, 0),
            self.series('256265', 'day', datetime.date(2015, 1, 1), datetime.date(2099, 1, 1), 0),
            self.series('408065', 'day', datetime.date(2015, 1, 1), None, 0),
            self.series('884737', 'day', datetime.date(2026, 3, 1), datetime.date(2026, 9, 29), 0),
            self.series('341249', 'day', datetime.date(2026, 3, 1), datetime.date(2026, 9, 29), 0),
        ]
        answers = {
            '738561': {
                'candles': [
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
            },
            '500325': {
                'candles': [],
            },
            '13368834': 'InputException: invalid token',
            '884737': 'GeneralException: Something went wrong, please try again',
            '341249': 'NetworkException: Too many requests',
        }
        self.connection = StandInConnection([], pending_series)
        for row in pending_series:
            self.connection.progress.append(
                (
                    row[0],
                    row[1],
                ),
            )
        base.get_postgres = StandInPostgres(self.connection).get_postgres
        self.history_api = StandInHistoryAPI(answers)
        self.downloader = ExampleBrokerCandles(self.history_api)

    def series(self, token, interval, oldest_requested, latest, empty_streak):
        """Builds one progress row the way `claim` returns it.

        Args:
            token (str): The broker's instrument token.
            interval (str): The stored interval name.
            oldest_requested (datetime.date | None): The earliest day asked for so far, or None before the first window.
            latest (datetime.date | None): The day of the newest bar stored, or None when none is.
            empty_streak (int): How many empty windows in a row the series has had.

        Returns:
            tuple: The (token, interval, earliest, latest, oldest requested, empty streak, failures) row.
        """
        oldest_requested_time = None
        if oldest_requested is not None:
            oldest_requested_time = datetime.datetime.combine(oldest_requested, datetime.time(), INDIA)
        latest_time = None
        if latest is not None:
            latest_time = datetime.datetime.combine(latest, datetime.time(), INDIA)
        return (
            token,
            interval,
            None,
            latest_time,
            oldest_requested_time,
            empty_streak,
            0,
        )

    def run(self):
        """Drains the queue, prints each series' outcome, then shows a run stopped before it starts.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(levelname)s %(name)s: %(message)s', force=True)
        visits, bars = self.downloader.run()
        print(f'Windows visited: {visits}, bars stored: {bars}')
        print(f'Tokens requested from the broker: {self.history_api.requests}')
        print('Outcome recorded for each series:')
        for token, interval, outcome in self.connection.outcomes:
            print(f'  {token} {interval}: {outcome}')
        print(f'Summary: {self.downloader.summary()}')
        stop_event = threading.Event()
        stop_event.set()
        print(f'A run asked to stop before it starts: {self.downloader.run(stop_event=stop_event)}')
        self.downloader.close()


if __name__ == '__main__':
    RunUntilTheQueueIsDrainedExample().run()
