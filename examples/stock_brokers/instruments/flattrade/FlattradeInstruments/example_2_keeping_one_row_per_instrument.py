"""Cleans Flattrade's downloaded master the way `ingest` does before storing it, keeping one row per instrument.

Before it writes anything, `ingest` runs five steps from `BrokerInstruments` on the downloaded frame: `normalize_columns`, `strip_whitespace`, `drop_unnamed_columns`, `drop_garbage_rows` and `dedupe`. `FlattradeInstruments` itself decides only what `dedupe` treats as one instrument, through `DEDUPE_KEY_COLUMNS`, and which row it keeps, through `DEDUPE_SORT_COLUMN`: the key is exchange and trading symbol together, sorted on `instrument` first, so the two blank footer rows of the BSE file, which share an empty exchange and trading symbol, also collapse into one.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there. The canned file repeats one instrument, so `dedupe` has a row to drop. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice the column names after `normalize_columns`, which are the names of the table's columns, and the line `dedupe` prints about the row it dropped.

Run it from the project root:

    python examples/stock_brokers/instruments/flattrade/FlattradeInstruments/example_2_keeping_one_row_per_instrument.py
"""

import io
import unittest.mock

import pandas

from stock_brokers.instruments.flattrade import (
    FlattradeInstruments,
)

PUBLISHED_FILES = {
    'NSE_Equity.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
        'NSE,1594,1,INFY,INFY-EQ,EQ,,,\n'
        'NSE,11536,1,TCS,TCS-EQ,EQ,,,\n'
        'NSE,1594,1,INFY,INFY-EQ,EQ,,,\n'
    ),
    'Nfo_Equity_Derivatives.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
        'NFO,52210,400,INFY,INFY27OCT26F,FUTSTK,27-OCT-2026,,XX\n'
    ),
    'Nfo_Index_Derivatives.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
        'NFO,52175,75,NIFTY,NIFTY27OCT26F,FUTIDX,27-OCT-2026,,XX\n'
    ),
    'Currency_Derivatives.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
        'CDS,1201,1,USDINR,USDINR29OCT26F,FUTCUR,29-OCT-2026,,XX\n'
    ),
    'Commodity.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
        'MCX,451669,1,CRUDEOIL,CRUDEOIL19OCT26,FUTCOM,19-OCT-2026,,XX\n'
    ),
    'BSE_Equity.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
        'BSE,500209,1,INFY,INFY,A,,,\n'
        ',,,,,,,,\n'
        ',,,,,,,,\n'
    ),
    'Bfo_Index_Derivatives.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
        'BFO,1135463,20,SENSEX,SENSEX30OCT26F,FUTIDX,30-OCT-2026,,XX\n'
    ),
    'Bfo_Equity_Derivatives.csv': (
        'Exchange,Token,Lotsize,Symbol,Tradingsymbol,Instrument,Expiry,Strike,Optiontype\n'
    ),
}

SHOWN_COLUMNS = [
    'exchange',
    'token',
    'tradingsymbol',
    'instrument',
    'lotsize',
]


class PublishedFiles:
    """A stand-in for `pandas.read_csv` that answers each of Flattrade's URLs with a canned file.

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
        published_files (PublishedFiles): The stand-in for Flattrade's published files.
        instruments (FlattradeInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.published_files = PublishedFiles(PUBLISHED_FILES)
        self.instruments = FlattradeInstruments()

    def run(self):
        """Downloads the master, cleans it and prints the rows that would be stored.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(pandas, 'read_csv', self.published_files.read_csv):
            frame = self.instruments.download()
        print(f'Rows downloaded: {len(frame)}')
        print(f'Key columns: {FlattradeInstruments.DEDUPE_KEY_COLUMNS}, sorted first on: {FlattradeInstruments.DEDUPE_SORT_COLUMN}')
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
