"""Downloads Stoxkart's instrument master with `StoxkartInstruments.download`, from canned files instead of the network.

Stoxkart publishes one public CSV file. `download` reads it with `pandas.read_csv`, every value as text so that nothing is coerced on the way in, and returns one frame. `ingest` then cleans that frame and stores it in `stoxkart.instruments`.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice which files were read, and that the headers arrive exactly as Stoxkart wrote them, with capitals and spaces, and `ingest` normalizes them only afterwards.

Run it from the project root:

    python examples/stock_brokers/instruments/stoxkart/StoxkartInstruments/example_1_downloading_the_master.py
"""

import io
import unittest.mock

import pandas

from stock_brokers.instruments.stoxkart import (
    StoxkartInstruments,
)

PUBLISHED_FILES = {
    'https://openapi.stoxkart.com/scrip-master/csv': (
        'Exchange,Market Segment Id,Token,Symbol,Symbol Description,Series,Instrument Type,Option Type,Expiry Date,Lot Size,Strike Price,ISIN Code,Tick Size\n'
        'NSE,1,1594,INFY,INFOSYS LIMITED,EQ,,,,1,,INE009A01021,0.10\n'
        'NSE,1,11536,TCS,TATA CONSULTANCY SERV LT,EQ,,,,1,,INE467B01029,0.10\n'
        'BSE,3,500209,INFY,INFOSYS LTD,A,,,,1,,INE009A01021,0.05\n'
        'NFO,2,52175,NIFTY,NIFTY 27OCT2026 FUT,,FUTIDX,XX,27-Oct-2026,75,,,0.10\n'
    ),
}


class PublishedFiles:
    """A stand-in for `pandas.read_csv` that answers each of Stoxkart's URLs with a canned file.

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
        published_files (PublishedFiles): The stand-in for Stoxkart's published files.
        instruments (StoxkartInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.published_files = PublishedFiles(PUBLISHED_FILES)
        self.instruments = StoxkartInstruments()

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
