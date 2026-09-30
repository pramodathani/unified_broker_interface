"""Lists Dhan's instruments as download identifiers, reads what an identifier says about its instrument, and classifies Dhan's refusals.

Dhan's security id is not unique on its own: 2885 is RELIANCE in the NSE cash segment and an old currency option in another. So `instruments` joins the security id, Dhan's exchange segment name and the instrument type into one identifier, leaving out any segment Dhan does not chart. The program gives the downloader a stand-in database connection whose cursor returns four rows as the instrument master query would, one of them in NSE's commodity segment, which Dhan lists but cannot chart and which is therefore dropped.

`identifier_parts` takes an identifier apart again and `series_context` reads its exchange and segments; the latter is a classmethod, so it needs no downloader at all.

Last, the program fetches through a stand-in for `DhanAPI` that raises the `DhanAPIException` each of three refusals produces. `Data_Error` is Dhan's answer for an empty window, so it comes back as no bars rather than an error; `Input_Exception` naming missing fields is what an expired contract gets, so the series is retired; and `Invalid_Authentication` means the session is dead. The downloader is built without its constructor, as in `test_runs/candle_parse.py`, so nothing connects to PostgreSQL or logs in.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/dhan/DhanCandles/example_2_identifiers_and_refusals.py
"""

import datetime

from stock_brokers.api.dhan import (
    DhanAPIException,
)
from stock_brokers.instruments.historical.base import (
    CandleError,
)
from stock_brokers.instruments.historical.dhan import (
    DhanCandles,
)


class InstrumentMasterCursor:
    """A stand-in database cursor that answers the instrument master query with fixed rows.

    Attributes:
        rows (list): The rows `fetchall` returns.
    """

    def __init__(self, rows):
        """Holds the rows to answer with.

        Args:
            rows (list): Tuples of (exchange, segment, security id, instrument, expiry).

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            InstrumentMasterCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Leaves the `with` block without suppressing an exception.

        Args:
            exception_type (type | None): The exception's class, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (types.TracebackType | None): Its traceback, if one was raised.

        Returns:
            bool: Always False.
        """
        return False

    def execute(self, query):
        """Accepts the query without running it.

        Args:
            query (str): The SQL the downloader sent.

        Returns:
            None: This method returns nothing.
        """

    def fetchall(self):
        """Returns the fixed rows.

        Returns:
            list: The rows.
        """
        return self.rows


class InstrumentMasterConnection:
    """A stand-in PostgreSQL connection over a few rows of Dhan's instrument master.

    Attributes:
        rows (list): The rows every cursor answers with.
    """

    def __init__(self):
        """Builds the connection with four instrument master rows.

        Returns:
            None: This method returns nothing.
        """
        self.rows = [
            (
                'NSE',
                'E',
                '2885',
                'EQUITY',
                None,
            ),
            (
                'NSE',
                'I',
                '13',
                'INDEX',
                None,
            ),
            (
                'MCX',
                'M',
                '565899',
                'FUTCOM',
                '2026-10-19',
            ),
            (
                'NSE',
                'M',
                '801234',
                'OPTFUT',
                '2026-10-27',
            ),
        ]

    def cursor(self):
        """Opens a cursor.

        Returns:
            InstrumentMasterCursor: A cursor over the rows.
        """
        return InstrumentMasterCursor(self.rows)

    def commit(self):
        """Accepts a commit.

        Returns:
            None: This method returns nothing.
        """


class RefusingDhanAPI:
    """A stand-in for `DhanAPI` that refuses with a chosen Dhan error.

    Attributes:
        error_type (str): Dhan's error type to refuse with.
        error_message (str): Dhan's error message to refuse with.
    """

    def __init__(self, error_type, error_message):
        """Holds the refusal to raise.

        Args:
            error_type (str): Dhan's error type, such as `Data_Error`.
            error_message (str): Dhan's error message.

        Returns:
            None: This method returns nothing.
        """
        self.error_type = error_type
        self.error_message = error_message

    def post(self, url, json=None):
        """Refuses a POST request.

        Args:
            url (str): The endpoint the downloader called.
            json (dict): The request body it sent.

        Returns:
            dict: Never returns.

        Raises:
            DhanAPIException: Always, carrying the chosen type and message.
        """
        raise DhanAPIException(code=self.error_type, message=self.error_message)


class IdentifiersAndRefusalsExample:
    """Lists identifiers, reads them, and classifies three refusals.

    Attributes:
        candles (DhanCandles): The downloader being shown.
    """

    def __init__(self):
        """Builds the downloader around the stand-in connection without running its constructor.

        Returns:
            None: This method returns nothing.
        """
        self.candles = object.__new__(DhanCandles)
        self.candles._connection = InstrumentMasterConnection()

    def show_identifiers(self):
        """Lists the instruments and reads each identifier.

        Returns:
            None: This method returns nothing.
        """
        instruments = self.candles.instruments()
        print(f'Instruments to download: {len(instruments)} of 4 rows')
        for identifier, instrument_type, expiry in instruments:
            security_id, exchange_segment, _ = self.candles.identifier_parts(identifier)
            context = DhanCandles.series_context(identifier)
            print(f'{identifier}: security id {security_id} in {exchange_segment}, exchange {context.exchange}, {len(context.segments)} segments to search, expiry {expiry}')

    def show_refusals(self):
        """Fetches through three refusing stand-ins and prints what each became.

        Returns:
            None: This method returns nothing.
        """
        refusals = [
            (
                'Data_Error',
                'System is unable to fetch data due to incorrect parameters or no data present',
            ),
            (
                'Input_Exception',
                'Missing required fields, bad values for parameters etc.',
            ),
            (
                'Invalid_Authentication',
                'Client ID or user generated access token is invalid or expired.',
            ),
        ]
        for error_type, error_message in refusals:
            self.candles._api = RefusingDhanAPI(error_type, error_message)
            try:
                payload = self.candles.fetch_candles(
                    '52175|NSE_FNO|FUTSTK',
                    '5minute',
                    datetime.date(2024, 1, 1),
                    datetime.date(2024, 3, 30),
                )
                outcome = f'empty window, {len(self.candles.parse_response(payload, "5minute"))} bars'
            except CandleError as error:
                outcome = type(error).__name__
            print(f'{error_type}: {outcome}')

    def run(self):
        """Runs both parts in turn.

        Returns:
            None: This method returns nothing.
        """
        self.show_identifiers()
        self.show_refusals()


if __name__ == '__main__':
    IdentifiersAndRefusalsExample().run()
