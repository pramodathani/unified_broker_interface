"""Downloads Groww's instrument master with `GrowwInstruments.download`, from canned files instead of the network.

Groww publishes one public CSV file. `download` reads it with `pandas.read_csv`, every value as text so that nothing is coerced on the way in, and returns one frame. `ingest` then cleans that frame and stores it in `groww.instruments`.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice which files were read, and that every value arrives as text, including numbers such as the exchange token, and an empty field arrives as a missing value.

Run it from the project root:

    python examples/stock_brokers/instruments/groww/GrowwInstruments/example_1_downloading_the_master.py
"""

import io
import unittest.mock

import pandas

from stock_brokers.instruments.groww import (
    GrowwInstruments,
)

PUBLISHED_FILES = {
    'https://growwapi-assets.groww.in/instruments/instrument.csv': (
        'exchange,exchange_token,trading_symbol,groww_symbol,name,instrument_type,segment,series,isin,underlying_symbol,underlying_exchange_token,expiry_date,strike_price,lot_size,tick_size,freeze_quantity,is_reserved,buy_allowed,sell_allowed,internal_trading_symbol,is_intraday\n'
        'NSE,1594,INFY,NSE-INFY,Infosys,EQ,CASH,EQ,INE009A01021,,,,,1,0.1,,0,1,1,INFY,1\n'
        'BSE,500209,INFY,BSE-INFY,Infosys,EQ,CASH,A,INE009A01021,,,,,1,0.05,,0,1,1,INFY,1\n'
        'NSE,11536,TCS,NSE-TCS,Tata Consultancy Services,EQ,CASH,EQ,INE467B01029,,,,,1,0.1,,0,1,1,TCS,1\n'
        'NSE,52175,NIFTY26OCTFUT,NSE-NIFTY-27Oct26-FUT,NIFTY,FUT,FNO,,,NIFTY,26000,2026-10-27,,75,0.1,1800,0,1,1,NIFTY26OCTFUT,1\n'
    ),
}


class PublishedFiles:
    """A stand-in for `pandas.read_csv` that answers each of Groww's URLs with a canned file.

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
        published_files (PublishedFiles): The stand-in for Groww's published files.
        instruments (GrowwInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.published_files = PublishedFiles(PUBLISHED_FILES)
        self.instruments = GrowwInstruments()

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
