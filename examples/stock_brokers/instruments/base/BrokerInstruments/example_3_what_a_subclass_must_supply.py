"""Shows the two things `BrokerInstruments` refuses to guess: the broker's name and how to download its file.

`BrokerInstruments` is a base class. Its constructor raises `NotImplementedError` when a subclass has not set `BROKER_NAME`, because the name is also the PostgreSQL schema the rows are written to, and its `download` raises `NotImplementedError` until a subclass overrides it. Both fail at once, before any file is fetched or any row is written.

The program defines one subclass that forgets the name and one that sets it but forgets `download`, and prints what each refusal says. Building the second ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice that the second ingester is built without complaint and fails only when `download` is called, and that both messages name the subclass at fault.

Run it from the project root:

    python examples/stock_brokers/instruments/base/BrokerInstruments/example_3_what_a_subclass_must_supply.py
"""

from stock_brokers.instruments.base import (
    BrokerInstruments,
)


class NamelessInstruments(BrokerInstruments):
    """An ingester that forgot to set `BROKER_NAME`."""


class UndownloadableInstruments(BrokerInstruments):
    """An ingester that names its broker but forgot to implement `download`."""

    BROKER_NAME = 'demo'


class WhatASubclassMustSupplyExample:
    """Builds the two incomplete ingesters and prints each refusal."""

    def run(self):
        """Tries each incomplete ingester and prints what it raises.

        Returns:
            None: This method returns nothing.
        """
        try:
            NamelessInstruments()
        except NotImplementedError as error:
            print(f'Building NamelessInstruments: {error}')
        instruments = UndownloadableInstruments()
        print(f'Built UndownloadableInstruments for table {instruments.table}')
        try:
            instruments.download()
        except NotImplementedError as error:
            print(f'Calling download: {error}')


if __name__ == '__main__':
    WhatASubclassMustSupplyExample().run()
