"""Logs in again once when the broker refuses the session in the middle of a download, and stops the broker when that does not help.

A broker session expires every day, and a download that runs for weeks meets that expiry every day. When `fetch_candles` raises `CandleAuthenticationError`, the base class calls `relogin` once and asks for the same window again; `relogin` goes through `ensure_session`, rebuilds the broker's API object around the new session, and calls `after_relogin` so that a downloader can renew anything it keeps on top of the session. Only if the fresh session is refused as well does the error reach `run`, which then stops the broker rather than send thousands of refused requests.

The real `ensure_session` takes a Redis lock and may drive a headless browser through a broker's login, which an example must never do. So this program replaces `ensure_session` in `stock_brokers.api.utilities.session` with a stand-in session store that simply issues a new token, and its made-up broker, `ExampleBrokerCandles`, overrides the private `_build_api` to wrap a stand-in history API around whatever token the store holds. The base class's constructor would open a PostgreSQL connection, and the example runner points PostgreSQL at a closed port, so `get_postgres` in the base module is replaced with a stand-in that hands out an in-memory connection, as in the other examples.

What to notice in the output: the first window is refused with the old token, fetched again after one login, and stored; `after_relogin` renews the downloader's market data token each time a login happens; a login that fails comes back as `CandleAuthenticationError` with the underlying error named in its message; and when the broker refuses even a fresh session, `run` stops on the first series, counting no visit and leaving the second series unclaimed, instead of carrying on through the queue.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/BrokerCandles/example_3_logging_in_again_after_a_refused_session.py
"""

import datetime
import logging
import sys
import zoneinfo

from stock_brokers.api.utilities import session
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


class StandInSessionStore:
    """A stand-in for the stored broker login, issuing a new token on every login.

    Attributes:
        valid_token (str): The token the broker currently accepts.
        stored_token (str): The token the downloader will be built around.
        logins (int): How many logins have been made.
        refuse_logins (bool): Whether a login attempt fails.
    """

    def __init__(self):
        """Builds the store holding a token that has already expired.

        Returns:
            None: This method returns nothing.
        """
        self.valid_token = 'token-issued-this-morning'
        self.stored_token = 'token-from-yesterday'
        self.logins = 0
        self.refuse_logins = False

    def ensure_session(self, broker_name, force=False, logger=None):
        """Logs in, in the place of `stock_brokers.api.utilities.session.ensure_session`.

        Args:
            broker_name (str): The broker to log in to.
            force (bool): Whether to skip the login rate limiter, which the stand-in ignores.
            logger (logging.Logger | None): Where progress would be reported.

        Returns:
            dict: The stored login document after the call.

        Raises:
            RuntimeError: When the store is set to refuse logins.
        """
        del force, logger
        if self.refuse_logins:
            raise RuntimeError(f'the {broker_name} login page did not accept the TOTP')
        self.logins += 1
        self.valid_token = f'token-from-login-{self.logins}'
        self.stored_token = self.valid_token
        return {
            'broker_name': broker_name,
            'access_token': self.stored_token,
        }


class StandInHistoryAPI:
    """A stand-in for a broker's history endpoint that accepts only the current token.

    Attributes:
        access_token (str): The token this API object was built with.
        session_store (StandInSessionStore): Which token the broker accepts.
        broker_refuses_everything (bool): Whether even a current token is refused.
    """

    def __init__(self, access_token, session_store, broker_refuses_everything):
        """Builds an API object around one token.

        Args:
            access_token (str): The token this API object sends.
            session_store (StandInSessionStore): Which token the broker accepts.
            broker_refuses_everything (bool): Whether even a current token is refused.

        Returns:
            None: This method returns nothing.
        """
        self.access_token = access_token
        self.session_store = session_store
        self.broker_refuses_everything = broker_refuses_everything

    def historical_data(self, token, interval, start_date, end_date):
        """Answers with two daily candles, or refuses a token that is not current.

        Args:
            token (str): The broker's instrument token.
            interval (str): The broker's interval code.
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            dict: The decoded response, with a `candles` list.

        Raises:
            PermissionError: When the token is not the one the broker accepts.
        """
        del token, interval, start_date, end_date
        print(f'  broker asked with {self.access_token}')
        if self.broker_refuses_everything or self.access_token != self.session_store.valid_token:
            raise PermissionError('TokenException: Incorrect `api_key` or `access_token`.')
        return {
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
        }


class ExampleBrokerCandles(base.BrokerCandles):
    """A made-up broker's candle download whose history endpoint needs a market data token minted from the session.

    Attributes:
        session_store (StandInSessionStore): The stand-in stored login.
        broker_refuses_everything (bool): Whether the stand-in broker refuses even a fresh session.
        market_data_token (str): The second credential, renewed after every login.
    """

    BROKER_NAME = 'example_broker'
    INTERVALS = {
        'day': 'day',
    }
    MAXIMUM_WINDOW_DAYS = {
        'day': 365,
    }
    REQUESTS_PER_SECOND = 50.0
    EARLIEST_AVAILABLE_DATE = datetime.date(2015, 1, 1)

    def __init__(self, session_store, broker_refuses_everything):
        """Builds the downloader around the stored login.

        Args:
            session_store (StandInSessionStore): The stand-in stored login.
            broker_refuses_everything (bool): Whether the stand-in broker refuses even a fresh session.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.session_store = session_store
        self.broker_refuses_everything = broker_refuses_everything
        self._api = self._build_api()
        self.market_data_token = f'market-data-for-{session_store.stored_token}'

    def _build_api(self):
        """Builds the stand-in history API around whatever token is stored now.

        Returns:
            StandInHistoryAPI: The API object.
        """
        return StandInHistoryAPI(self.session_store.stored_token, self.session_store, self.broker_refuses_everything)

    def after_relogin(self):
        """Renews the market data token from the new session.

        Returns:
            None: This method returns nothing.
        """
        self.market_data_token = f'market-data-for-{self.session_store.stored_token}'
        print(f'  renewed the market data token: {self.market_data_token}')

    def fetch_candles(self, token, interval, start_date, end_date):
        """Fetches one window of candles, turning a refused token into a candle error.

        Args:
            token (str): The broker's instrument token.
            interval (str): The stored interval name.
            start_date (datetime.date): The first day of the window.
            end_date (datetime.date): The last day of the window.

        Returns:
            dict: The decoded response.

        Raises:
            CandleAuthenticationError: When the broker refuses the session.
        """
        try:
            return self._api.historical_data(token, self.INTERVALS[interval], start_date, end_date)
        except PermissionError as error:
            raise base.CandleAuthenticationError(str(error)) from error

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
            bars.append(
                (
                    moment,
                    candle[1],
                    candle[2],
                    candle[3],
                    candle[4],
                    candle[5],
                    None,
                ),
            )
        return bars


class LoggingInAgainAfterARefusedSessionExample:
    """Shows a refused session recovered by one login, a failed login, and a broker that refuses every session.

    Attributes:
        session_store (StandInSessionStore): The stand-in stored login.
    """

    def __init__(self):
        """Puts the stand-in login in place of the real one.

        Returns:
            None: This method returns nothing.
        """
        self.session_store = StandInSessionStore()
        session.ensure_session = self.session_store.ensure_session

    def series(self, token):
        """Builds one daily series' progress row, part way through its backward walk.

        Args:
            token (str): The broker's instrument token.

        Returns:
            tuple: The (token, interval, earliest, latest, oldest requested, empty streak, failures) row.
        """
        return (
            token,
            'day',
            datetime.datetime(2026, 3, 2, tzinfo=INDIA),
            datetime.datetime(2026, 9, 29, tzinfo=INDIA),
            datetime.datetime(2026, 3, 1, tzinfo=INDIA),
            0,
            0,
        )

    def downloader_over(self, connection, broker_refuses_everything):
        """Builds a downloader whose database connection is the given stand-in.

        Args:
            connection (StandInConnection): The in-memory database.
            broker_refuses_everything (bool): Whether the stand-in broker refuses even a fresh session.

        Returns:
            ExampleBrokerCandles: The downloader.
        """
        base.get_postgres = StandInPostgres(connection).get_postgres
        return ExampleBrokerCandles(self.session_store, broker_refuses_everything)

    def run(self):
        """Runs the three situations in turn and prints what each did.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(levelname)s %(name)s: %(message)s', force=True)
        connection = StandInConnection([], [])
        downloader = self.downloader_over(connection, False)
        print(f'Built with {downloader.market_data_token}')
        print('Visiting one window with yesterday\'s token:')
        stored = downloader.visit(self.series('738561'))
        print(f'Bars stored: {stored}, logins made: {self.session_store.logins}')
        print(f'Progress updates: {connection.outcomes}')
        print('Logging in again by hand:')
        downloader.relogin()
        print('Renewing the market data token by hand, without a login:')
        downloader.after_relogin()
        self.session_store.refuse_logins = True
        print('Logging in again when the login itself fails:')
        try:
            downloader.relogin()
        except base.CandleAuthenticationError as error:
            print(f'  CandleAuthenticationError: {error}')
        downloader.close()

        self.session_store.refuse_logins = False
        print('Running a queue of two series against a broker that refuses every session:')
        connection = StandInConnection(
            [],
            [
                self.series('738561'),
                self.series('2953217'),
            ],
        )
        downloader = self.downloader_over(connection, True)
        visits, bars = downloader.run()
        print(f'Windows visited: {visits}, bars stored: {bars}, series left in the queue: {len(connection.pending_series)}')
        print(f'Progress updates: {connection.outcomes}')
        downloader.close()


if __name__ == '__main__':
    LoggingInAgainAfterARefusedSessionExample().run()
