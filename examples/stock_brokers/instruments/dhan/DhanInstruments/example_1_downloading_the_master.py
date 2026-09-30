"""Downloads Dhan's instrument master with `DhanInstruments.download`, from canned files instead of the network.

Dhan publishes one public detailed scrip master CSV file, every line of which ends with a trailing comma. `download` reads it with `pandas.read_csv`, every value as text so that nothing is coerced on the way in, and returns one frame. `ingest` then cleans that frame and stores it in `dhan.instruments`.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice which files were read, and that Dhan's trailing comma arrives as an extra empty column named `Unnamed: 16`, which `ingest` later drops because it is empty on every row. Notice also that the literal `NA` Dhan writes in the futures row's ISIN arrives as a missing value, because `read_csv` treats `NA` as missing even when every value is read as text.

Run it from the project root:

    python examples/stock_brokers/instruments/dhan/DhanInstruments/example_1_downloading_the_master.py
"""

import io
import unittest.mock

import pandas

from stock_brokers.instruments.dhan import (
    DhanInstruments,
)

PUBLISHED_FILES = {
    'https://images.dhan.co/api-data/api-scrip-master-detailed.csv': (
        'EXCH_ID,SEGMENT,SECURITY_ID,ISIN,INSTRUMENT,UNDERLYING_SECURITY_ID,UNDERLYING_SYMBOL,SYMBOL_NAME,DISPLAY_NAME,INSTRUMENT_TYPE,SERIES,LOT_SIZE,SM_EXPIRY_DATE,STRIKE_PRICE,OPTION_TYPE,TICK_SIZE,\n'
        'NSE,E,1594,INE009A01021,EQUITY,,INFY,INFOSYS LIMITED,Infosys,ES,EQ,1.0,,,,0.1000,\n'
        'NSE,E,11536,INE467B01029,EQUITY,,TCS,TATA CONSULTANCY SERV LT,TCS,ES,EQ,1.0,,,,0.1000,\n'
        'BSE,E,500209,INE009A01021,EQUITY,,INFY,INFOSYS LTD,Infosys,ES,A,1.0,,,,0.0500,\n'
        'NSE,D,52175,NA,FUTIDX,26000,NIFTY,NIFTY-Oct2026-FUT,NIFTY OCT FUT,FUT,NA,75.0,2026-10-27,-0.01000,XX,0.1000,\n'
    ),
}


class PublishedFiles:
    """A stand-in for `pandas.read_csv` that answers each of Dhan's URLs with a canned file.

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
        published_files (PublishedFiles): The stand-in for Dhan's published files.
        instruments (DhanInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.published_files = PublishedFiles(PUBLISHED_FILES)
        self.instruments = DhanInstruments()

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
