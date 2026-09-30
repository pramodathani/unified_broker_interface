"""Downloads Flattrade's instrument master with `FlattradeInstruments.download`, from canned files instead of the network.

Flattrade publishes eight public CSV files, one per exchange segment. `download` reads each file with `pandas.read_csv`, every value as text so that nothing is coerced on the way in, and returns one frame, stacking the files in the order listed in the module. `ingest` then cleans that frame and stores it in `flattrade.instruments`.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice which files were read, and that the two blank footer lines at the end of the BSE file come back with an empty exchange, trading symbol and instrument rather than missing values, because `download` fills those three in so that `dedupe` has something to compare, and that the BSE equity derivatives file holds no rows that day.

Run it from the project root:

    python examples/stock_brokers/instruments/flattrade/FlattradeInstruments/example_1_downloading_the_master.py
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


class DownloadingTheMasterExample:
    """Downloads the master from the canned files and prints what came back.

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
        """Downloads the master and prints the files read and the frame returned.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(pandas, 'read_csv', self.published_files.read_csv):
            frame = self.instruments.download()
        print('Files read:')
        for source in self.published_files.sources_read:
            print(f'    {source}')
        print(f'Rows: {len(frame)}')
        print(f'Columns: {list(frame.columns)}')
        print('First six columns:')
        print(frame.iloc[:, :6].to_string())


if __name__ == '__main__':
    DownloadingTheMasterExample().run()
