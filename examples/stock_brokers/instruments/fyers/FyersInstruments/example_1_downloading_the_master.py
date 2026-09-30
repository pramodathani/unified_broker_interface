"""Downloads Fyers's instrument master with `FyersInstruments.download`, from canned files instead of the network.

Fyers publishes seven public CSV files, one per exchange segment, none of which has a header line. `download` reads each file with `pandas.read_csv`, every value as text so that nothing is coerced on the way in, and returns one frame, stacking the files in the order listed in the module. `ingest` then cleans that frame and stores it in `fyers.instruments`.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice which files were read, and that the headerless files take their column names from the module's `COLUMN_NAMES` list.

Run it from the project root:

    python examples/stock_brokers/instruments/fyers/FyersInstruments/example_1_downloading_the_master.py
"""

import io
import unittest.mock

import pandas

from stock_brokers.instruments.fyers import (
    FyersInstruments,
)

PUBLISHED_FILES = {
    'NSE_CD.csv': (
        '101126102901201,USDINR 26 Oct 29 FUT,11,1,0.0025,,0900-1700|1815-1915:,2026-09-29,1793269800,NSE:USDINR26OCTFUT,10,12,1201,USDINR,-1,-1.0,XX,-1,None,0,0.0\n'
    ),
    'NSE_FO.csv': (
        '101126102752175,NIFTY 26 Oct 27 FUT,11,75,0.1,,0915-1530|1815-1915:,2026-09-29,1793097000,NSE:NIFTY26OCTFUT,10,11,52175,NIFTY,26000,-1.0,XX,101000000026000,None,0,0.0\n'
    ),
    'NSE_COM.csv': (
        '101126102835001,CRUDEOIL 26 Oct 28 FUT,30,1,1.0,,0900-2330|1815-1915:,2026-09-29,1793183400,NSE:CRUDEOIL26OCTFUT,10,17,35001,CRUDEOIL,-1,-1.0,XX,-1,None,0,0.0\n'
    ),
    'NSE_CM.csv': (
        '10100000001594,INFOSYS LIMITED,0,1,0.1,INE009A01021,0915-1530|1815-1915:,2026-09-29,,NSE:INFY-EQ,10,10,1594,INFY,1594,-1.0,XX,10100000001594,None,0,0.0\n'
        '10100000011536,TATA CONSULTANCY SERV LT,0,1,0.1,INE467B01029,0915-1530|1815-1915:,2026-09-29,,NSE:TCS-EQ,10,10,11536,TCS,11536,-1.0,XX,10100000011536,None,0,0.0\n'
    ),
    'BSE_CM.csv': (
        '1210000000500209,INFOSYS LTD.,0,1,0.05,INE009A01021,0915-1530|1815-1915:,2026-09-29,,BSE:INFY-A,12,10,500209,INFY,500209,-1.0,XX,1210000000500209,None,0,0.0\n'
    ),
    'BSE_FO.csv': (
        '1211261030873765,SENSEX 26 Oct 30 FUT,11,20,0.05,,0915-1530|1815-1915:,2026-09-29,1793356200,BSE:SENSEX26OCTFUT,12,11,873765,SENSEX,1,-1.0,XX,12100000000001,None,0,0.0\n'
    ),
    'MCX_COM.csv': (
        '1120261019451669,CRUDEOIL 26 Oct 19 FUT,30,1,1.0,,0900-2330|1815-1915:,2026-09-29,1792425600,MCX:CRUDEOIL26OCTFUT,11,20,451669,CRUDEOIL,294,-1.0,XX,1120000000000294,None,0,0.0\n'
    ),
}


class PublishedFiles:
    """A stand-in for `pandas.read_csv` that answers each of Fyers's URLs with a canned file.

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
        published_files (PublishedFiles): The stand-in for Fyers's published files.
        instruments (FyersInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.published_files = PublishedFiles(PUBLISHED_FILES)
        self.instruments = FyersInstruments()

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
