"""Downloads Shoonya's instrument master from its seven ZIP archives, served from memory instead of the network.

Shoonya publishes one ZIP archive per exchange, each holding a single comma-separated text file. `ShoonyaInstruments.download` fetches every archive with `requests.get`, reads each `.txt` or `.csv` file inside as latin-1 text, adds `source_zip_url` and `source_file_name` columns saying where each row came from, and stacks the files. The exchanges' files have different columns, so a column missing from one file is a missing value in its rows.

The program must not download anything, so `requests.get` is replaced, only while `download` runs, by `ArchiveServer`, a stand-in that builds each archive in memory from a few recorded-looking lines and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice the two columns `download` adds, that the NCX archive holds no rows that day, and that the trailing comma on every line of Shoonya's files arrives as an empty column named after its position, `Unnamed: 7`, `Unnamed: 10` or `Unnamed: 11` depending on the file's width, all of which `ingest` later drops because they are empty on every row.

Run it from the project root:

    python examples/stock_brokers/instruments/shoonya/ShoonyaInstruments/example_1_downloading_the_zip_archives.py
"""

import io
import unittest.mock
import zipfile

import requests

from stock_brokers.instruments.shoonya import (
    ShoonyaInstruments,
)

ARCHIVE_CONTENTS = {
    'NSE_symbols.txt.zip': (
        'Exchange,Token,LotSize,Symbol,TradingSymbol,Instrument,TickSize,\n'
        'NSE,1594,1,INFY,INFY-EQ,EQ,0.10,\n'
        'NSE,11536,1,TCS,TCS-EQ,EQ,0.10,\n'
    ),
    'NFO_symbols.txt.zip': (
        'Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize,\n'
        'NFO,52175,75,NIFTY,NIFTY27OCT26F,27-OCT-2026,FUTIDX,XX,0,0.10,\n'
    ),
    'CDS_symbols.txt.zip': (
        'Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize,\n'
        'CDS,1201,1,USDINR,USDINR29OCT26F,29-OCT-2026,FUTCUR,XX,0,0.0025,\n'
    ),
    'MCX_symbols.txt.zip': (
        'Exchange,Token,LotSize,GNGD,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize,\n'
        'MCX,451669,100,1,CRUDEOIL,CRUDEOIL19OCT26,19-OCT-2026,FUTCOM,XX,0,1.00,\n'
    ),
    'BSE_symbols.txt.zip': (
        'Exchange,Token,LotSize,Symbol,TradingSymbol,Instrument,TickSize,\n'
        'BSE,500209,1,INFY,INFY,A,0.05,\n'
    ),
    'BFO_symbols.txt.zip': (
        'Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize,\n'
        'BFO,1135463,20,SENSEX,SENSEX30OCT26F,30-OCT-2026,FUTIDX,XX,0,0.05,\n'
    ),
    'NCX_symbols.txt.zip': (
        'Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize,\n'
    ),
}


class ArchiveServer:
    """A stand-in for `requests.get` that serves each of Shoonya's archives, built in memory from canned text.

    Attributes:
        contents (dict): Each archive's file name mapped to the text of the file inside it.
        urls_asked (list): Every URL requested, in order.
    """

    def __init__(self, contents):
        """Holds the canned file contents.

        Args:
            contents (dict): Each archive's file name mapped to the text of the file inside it.

        Returns:
            None: This method returns nothing.
        """
        self.contents = contents
        self.urls_asked = []

    def archive(self, archive_name):
        """Builds one ZIP archive holding the canned text file for that archive.

        Args:
            archive_name (str): The archive's file name, such as `NSE_symbols.txt.zip`.

        Returns:
            bytes: The archive.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(archive_name.removesuffix('.zip'), self.contents[archive_name])
        return buffer.getvalue()

    def get(self, url, timeout=None):
        """Serves one archive, in place of `requests.get`.

        Args:
            url (str): The archive's URL.
            timeout (float | None): The timeout, which the stand-in ignores.

        Returns:
            requests.Response: A successful answer carrying the archive.
        """
        self.urls_asked.append(url)
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = 'application/zip'
        response._content = self.archive(url.rsplit('/', 1)[1])
        response.url = url
        return response


class DownloadingTheZipArchivesExample:
    """Downloads the master from the in-memory archives and prints what came back.

    Attributes:
        server (ArchiveServer): The stand-in for Shoonya's file server.
        instruments (ShoonyaInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in server and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.server = ArchiveServer(ARCHIVE_CONTENTS)
        self.instruments = ShoonyaInstruments()

    def run(self):
        """Downloads the master and prints the archives asked for and the rows returned.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(requests, 'get', self.server.get):
            frame = self.instruments.download()
        print('Archives asked for:')
        for url in self.server.urls_asked:
            print(f'    {url}')
        print(f'Rows: {len(frame)}')
        print(f'Columns: {list(frame.columns)}')
        shown_columns = [
            'Exchange',
            'Token',
            'TradingSymbol',
            'Instrument',
            'source_file_name',
        ]
        print(frame[shown_columns].to_string())


if __name__ == '__main__':
    DownloadingTheZipArchivesExample().run()
