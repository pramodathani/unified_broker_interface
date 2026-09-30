"""Writes a small broker ingester on `BrokerInstruments` and runs its cleaning steps one at a time.

A broker's instrument ingester subclasses `BrokerInstruments`, names the broker in `BROKER_NAME`, says which columns identify one instrument in `DEDUPE_KEY_COLUMNS`, and implements `download`. The base class supplies the cleaning steps that `ingest` runs on every download, in this order: `normalize_columns` turns header names into lowercase SQL identifiers, `strip_whitespace` trims padded text, `drop_unnamed_columns` drops the empty column that a trailing comma on every line creates, `drop_garbage_rows` drops exchange test instruments such as `NSETEST`, and `dedupe` keeps one row per instrument.

`DemoInstruments` is a made-up broker whose `download` reads a five-line master file from memory instead of the network. The file carries every blemish the cleaning steps exist for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice what the output shows about `strip_whitespace` and `drop_garbage_rows`. Both only touch columns whose dtype is `object`, but under pandas 3, which this project pins, `read_csv(dtype=str)` produces string columns whose dtype is not `object`. So on the frame as downloaded both steps change nothing: the padded symbols stay padded, the `NSETEST` row stays, and `dedupe` then treats ` INFY ` and `INFY` as different instruments. This is reported as a bug and the output records what the code does today. The program then runs the same steps again on a copy converted to `object` columns, which shows what they are meant to do: every value trimmed, the test instrument dropped, and one NSE INFY row kept. There `dedupe` sorts on `series` before keeping the first row of each instrument, so the `BE` row survives whatever order the broker listed the rows in.

Run it from the project root:

    python examples/stock_brokers/instruments/base/BrokerInstruments/example_1_cleaning_a_master_file.py
"""

import io

import pandas

from stock_brokers.instruments.base import (
    BrokerInstruments,
)

MASTER_FILE = (
    ' Exchange ,Trading Symbol,Series,Lot Size,\n'
    'NSE, INFY ,EQ,1,\n'
    'NSE,INFY,BE,1,\n'
    'NSE,NSETEST,EQ,1,\n'
    'BSE,INFY,A,1,\n'
    'NSE,TCS ,EQ,1,\n'
)


class DemoInstruments(BrokerInstruments):
    """A made-up broker's instrument ingester whose master file is held in memory."""

    BROKER_NAME = 'demo'
    DEDUPE_KEY_COLUMNS = [
        'exchange',
        'trading_symbol',
    ]
    DEDUPE_SORT_COLUMN = 'series'

    def download(self):
        """Reads the master file, every value as text, as a real ingester reads the broker's file.

        Returns:
            pandas.DataFrame: Every row of the file.
        """
        return pandas.read_csv(io.StringIO(MASTER_FILE), dtype=str)


class CleaningAMasterFileExample:
    """Runs each cleaning step on the downloaded file and prints the result after each.

    Attributes:
        instruments (DemoInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.instruments = DemoInstruments()

    def show(self, step, frame):
        """Prints a frame under the name of the step that produced it.

        Args:
            step (str): The step's name.
            frame (pandas.DataFrame): The frame after that step.

        Returns:
            None: This method returns nothing.
        """
        print(f'After {step}:')
        print(frame.to_string())
        print()

    def run(self):
        """Downloads the file and cleans it step by step.

        Returns:
            None: This method returns nothing.
        """
        print(f'Table: {self.instruments.table}')
        frame = self.instruments.download()
        print(f'Downloaded columns: {list(frame.columns)}')
        frame = self.instruments.normalize_columns(frame)
        self.show('normalize_columns', frame)
        frame = self.instruments.strip_whitespace(frame)
        print(f'Trading symbols after strip_whitespace: {list(frame["trading_symbol"])}')
        print()
        frame = self.instruments.drop_unnamed_columns(frame)
        self.show('drop_unnamed_columns', frame)
        frame = self.instruments.drop_garbage_rows(frame)
        self.show('drop_garbage_rows', frame)
        frame = self.instruments.dedupe(frame)
        self.show('dedupe', frame)
        print('The same steps on a copy with object columns:')
        frame = self.instruments.normalize_columns(self.instruments.download()).astype(object)
        frame = self.instruments.strip_whitespace(frame)
        frame = self.instruments.drop_unnamed_columns(frame)
        frame = self.instruments.drop_garbage_rows(frame)
        frame = self.instruments.dedupe(frame)
        self.show('all five steps', frame)


if __name__ == '__main__':
    CleaningAMasterFileExample().run()
