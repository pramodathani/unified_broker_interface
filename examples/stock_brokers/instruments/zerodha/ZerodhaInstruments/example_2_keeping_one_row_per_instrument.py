"""Cleans Zerodha's downloaded master the way `ingest` does before storing it, keeping one row per instrument.

Before it writes anything, `ingest` runs five steps from `BrokerInstruments` on the downloaded frame: `normalize_columns`, `strip_whitespace`, `drop_unnamed_columns`, `drop_garbage_rows` and `dedupe`. `ZerodhaInstruments` itself decides only what `dedupe` treats as one instrument, through `DEDUPE_KEY_COLUMNS`, and which row it keeps, through `DEDUPE_SORT_COLUMN`: Kite's instrument token is unique across every exchange, so it alone is the key and nothing has to be sorted first.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there. The canned file repeats one instrument, so `dedupe` has a row to drop. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice the column names after `normalize_columns`, which are the names of the table's columns, and the line `dedupe` prints about the row it dropped.

Run it from the project root:

    python examples/stock_brokers/instruments/zerodha/ZerodhaInstruments/example_2_keeping_one_row_per_instrument.py
"""

import io
import unittest.mock

import pandas

from stock_brokers.instruments.zerodha import (
    ZerodhaInstruments,
)

PUBLISHED_FILES = {
    'https://api.kite.trade/instruments': (
        'instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n'
        '408065,1594,INFY,INFOSYS,0,,0,0.1,1,EQ,NSE,NSE\n'
        '2953217,11536,TCS,TATA CONSULTANCY SERV LT,0,,0,0.1,1,EQ,NSE,NSE\n'
        '256265,1001,NIFTY 50,,0,,0,0,0,EQ,INDICES,NSE\n'
        '13874690,54198,NIFTY26OCTFUT,NIFTY,0,2026-10-27,0,0.1,75,FUT,NFO-FUT,NFO\n'
        '408065,1594,INFY,INFOSYS,0,,0,0.1,1,EQ,NSE,NSE\n'
    ),
}

SHOWN_COLUMNS = [
    'instrument_token',
    'tradingsymbol',
    'instrument_type',
    'segment',
    'exchange',
    'lot_size',
]


class PublishedFiles:
    """A stand-in for `pandas.read_csv` that answers each of Zerodha's URLs with a canned file.

    Attributes:
        files (dict): The end of each URL mapped to the text of the file served there.
        real_read_csv (Callable): The real `pandas.read_csv`, which parses the canned text.
        sources_read (list): Every URL asked for, in order.
    """

    def __init__(self, files):
        """Holds the canned files and keeps the real reader for parsing them.

        Args:
            files (dict): The end of each URL mapped to the text of the file served there.

        Returns:
            None: This method returns nothing.
        """
        self.files = files
        self.real_read_csv = pandas.read_csv
        self.sources_read = []

    def read_csv(self, source, **options):
        """Parses the canned file for a URL, in place of `pandas.read_csv`.

        Args:
            source (str): The URL `download` asked for.
            **options (Any): The parsing options `download` passed, such as `dtype`.

        Returns:
            pandas.DataFrame: The canned file, parsed with those options.

        Raises:
            KeyError: When no canned file matches the URL.
        """
        self.sources_read.append(source)
        for ending, text in self.files.items():
            if source.endswith(ending):
                return self.real_read_csv(io.StringIO(text), **options)
        raise KeyError(f'No canned file for {source}')


class KeepingOneRowPerInstrumentExample:
    """Downloads the master from the canned files and runs the cleaning steps `ingest` runs.

    Attributes:
        published_files (PublishedFiles): The stand-in for Zerodha's published files.
        instruments (ZerodhaInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.published_files = PublishedFiles(PUBLISHED_FILES)
        self.instruments = ZerodhaInstruments()

    def run(self):
        """Downloads the master, cleans it and prints the rows that would be stored.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(pandas, 'read_csv', self.published_files.read_csv):
            frame = self.instruments.download()
        print(f'Rows downloaded: {len(frame)}')
        print(f'Key columns: {ZerodhaInstruments.DEDUPE_KEY_COLUMNS}, sorted first on: {ZerodhaInstruments.DEDUPE_SORT_COLUMN}')
        frame = self.instruments.normalize_columns(frame)
        print(f'Columns after normalize_columns: {list(frame.columns)}')
        frame = self.instruments.strip_whitespace(frame)
        frame = self.instruments.drop_unnamed_columns(frame)
        frame = self.instruments.drop_garbage_rows(frame)
        frame = self.instruments.dedupe(frame)
        print(f'Rows to store: {len(frame)}')
        print(frame[SHOWN_COLUMNS].to_string())


if __name__ == '__main__':
    KeepingOneRowPerInstrumentExample().run()
