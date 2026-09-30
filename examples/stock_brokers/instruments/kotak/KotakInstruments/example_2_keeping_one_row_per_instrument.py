"""Cleans Kotak's downloaded master the way `ingest` does before storing it, keeping one row per instrument.

Before it writes anything, `ingest` runs five steps from `BrokerInstruments` on the downloaded frame: `normalize_columns`, `strip_whitespace`, `drop_unnamed_columns`, `drop_garbage_rows` and `dedupe`. `KotakInstruments` itself decides only what `dedupe` treats as one instrument, through `DEDUPE_KEY_COLUMNS`, and which row it keeps, through `DEDUPE_SORT_COLUMN`: the key is Kotak's exchange segment and trading symbol together, sorted on the instrument type first so that the row kept is predictable.

The program must not download anything, so `pandas.read_csv` is replaced, only while `download` runs, by `PublishedFiles`, a stand-in that answers each URL with a few recorded-looking lines of the file served there. The canned file repeats one instrument, so `dedupe` has a row to drop. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice the column names after `normalize_columns`, which are the names of the table's columns, and the line `dedupe` prints about the row it dropped.

Run it from the project root:

    python examples/stock_brokers/instruments/kotak/KotakInstruments/example_2_keeping_one_row_per_instrument.py
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
        '1594,EQ,nse_cm,,INFY,INFY-EQ,,INE009A01021,10.000000,1,,,NSE\n'
    ),
}

SHOWN_COLUMNS = [
    'psymbol',
    'pexchseg',
    'ptrdsymbol',
    'pinsttype',
    'llotsize',
    'dstrikeprice',
]


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


class KeepingOneRowPerInstrumentExample:
    """Downloads the master from the canned files and runs the cleaning steps `ingest` runs.

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
        """Downloads the master, cleans it and prints the rows that would be stored.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(pandas, 'read_csv', self.published_files.read_csv):
            frame = self.instruments.download()
        print(f'Rows downloaded: {len(frame)}')
        print(f'Key columns: {KotakInstruments.DEDUPE_KEY_COLUMNS}, sorted first on: {KotakInstruments.DEDUPE_SORT_COLUMN}')
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
