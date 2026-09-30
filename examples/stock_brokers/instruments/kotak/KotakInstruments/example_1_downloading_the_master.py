"""Downloads Kotak's instrument master with `KotakInstruments.download`, from canned files instead of the network.

Kotak publishes seven CSV files, five under a `transformed` folder and two under `transformed-v1`, all inside a folder named after today's date. `download` reads each file with `pandas.read_csv`, every value as text so that nothing is coerced on the way in, and returns one frame, stacking the files in the order listed in the module. `ingest` then cleans that frame and stores it in `kotak.instruments`.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there and remembers which URLs were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice which files were read, and that every URL carries today's date, which is why the output shows only the last two parts of each, that the `dStrikePrice;` header of this canned file arrives with a stray semicolon, the kind of punctuation `normalize_columns` later removes, and that the `nse_com` file holds no rows that day.

Run it from the project root:

    python examples/stock_brokers/instruments/kotak/KotakInstruments/example_1_downloading_the_master.py
"""

import io
import unittest.mock

import pandas

from stock_brokers.instruments.kotak import (
    KotakInstruments,
)

PUBLISHED_FILES = {
    'transformed/cde_fo.csv': (
        'pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,pOptionType,pISIN,dTickSize,lLotSize,lExpiryDate,dStrikePrice;,pExchange\n'
        '1201,,cde_fo,FUTCUR,USDINR,USDINR26OCTFUT,XX,,25.000000,1,1477328400,-1.000000,CDS\n'
    ),
    'transformed/mcx_fo.csv': (
        'pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,pOptionType,pISIN,dTickSize,lLotSize,lExpiryDate,dStrikePrice;,pExchange\n'
        '451669,,mcx_fo,FUTCOM,CRUDEOIL,CRUDEOIL26OCTFUT,XX,,100.000000,1,1476921600,-1.000000,MCX\n'
    ),
    'transformed/nse_fo.csv': (
        'pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,pOptionType,pISIN,dTickSize,lLotSize,lExpiryDate,dStrikePrice;,pExchange\n'
        '52175,,nse_fo,FUTIDX,NIFTY,NIFTY26OCTFUT,XX,,10.000000,75,1477594800,-1.000000,NSE\n'
    ),
    'transformed/bse_fo.csv': (
        'pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,pOptionType,pISIN,dTickSize,lLotSize,lExpiryDate,dStrikePrice;,pExchange\n'
        '1135463,,bse_fo,FUTIDX,SENSEX,SENSEX26OCTFUT,XX,,5.000000,20,1477767600,-1.000000,BSE\n'
    ),
    'transformed/nse_com.csv': (
        'pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,pOptionType,pISIN,dTickSize,lLotSize,lExpiryDate,dStrikePrice;,pExchange\n'
    ),
    'transformed-v1/bse_cm-v1.csv': (
        'pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,pOptionType,pISIN,dTickSize,lLotSize,lExpiryDate,dStrikePrice;,pExchange\n'
        '500209,A,bse_cm,,INFY,INFY,,INE009A01021,5.000000,1,,,BSE\n'
    ),
    'transformed-v1/nse_cm-v1.csv': (
        'pSymbol,pGroup,pExchSeg,pInstType,pSymbolName,pTrdSymbol,pOptionType,pISIN,dTickSize,lLotSize,lExpiryDate,dStrikePrice;,pExchange\n'
        '1594,EQ,nse_cm,,INFY,INFY-EQ,,INE009A01021,10.000000,1,,,NSE\n'
        '11536,EQ,nse_cm,,TCS,TCS-EQ,,INE467B01029,10.000000,1,,,NSE\n'
    ),
}


class PublishedFiles:
    """A stand-in for `pandas.read_csv` that answers each of Kotak's URLs with a canned file.

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
        published_files (PublishedFiles): The stand-in for Kotak's published files.
        instruments (KotakInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.published_files = PublishedFiles(PUBLISHED_FILES)
        self.instruments = KotakInstruments()

    def run(self):
        """Downloads the master and prints the files read and the frame returned.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(pandas, 'read_csv', self.published_files.read_csv):
            frame = self.instruments.download()
        print('Files read:')
        for source in self.published_files.sources_read:
            print(f'    ... {"/".join(source.split("/")[-2:])}')
        print(f'Rows: {len(frame)}')
        print(f'Columns: {list(frame.columns)}')
        print('First six columns:')
        print(frame.iloc[:, :6].to_string())


if __name__ == '__main__':
    DownloadingTheMasterExample().run()
