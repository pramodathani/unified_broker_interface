"""Downloads Zerodha's instrument master with `ZerodhaInstruments.download`, from canned files instead of the network.

Zerodha publishes one public CSV file covering every exchange Kite supports. `download` reads it with `pandas.read_csv`, every value as text so that nothing is coerced on the way in, and returns one frame. `ingest` then cleans that frame and stores it in `zerodha.instruments`.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice which files were read, and that every value arrives as text, including numbers such as the instrument token, and an empty field such as an equity's `expiry` arrives as a missing value.

Run it from the project root:

    python examples/stock_brokers/instruments/zerodha/ZerodhaInstruments/example_1_downloading_the_master.py
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
    ),
}


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


class DownloadingTheMasterExample:
    """Downloads the master from the canned files and prints what came back.

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
