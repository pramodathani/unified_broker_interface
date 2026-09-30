"""Reads Stoxkart's `lot_size` on NSE and BSE currencies and NCDEX for a few contracts through a stand-in connection.

`read` runs the source's query and returns, for each contract, the set of distinct sizes its rows give, as decimals with trailing zeros removed. The rows give a BSE USDINR future at 1000 units and two NCDEX futures, DHANIYA and JEERA, at 5 and 3 tonnes.

The connection is a small stand-in that returns the rows it was built with and records the parameters of the query, so the program needs no database. The parameters show that the query is limited to Stoxkart's rows on the trusted exchange labels.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/StoxkartLotSizeSource/example_2_reading_sizes.py
"""

import datetime
import types

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    StoxkartLotSizeSource,
)


class StandInConnection:
    """A stand-in for a database connection that returns fixed rows and records the parameters of each query.

    Attributes:
        rows (list): The rows every query returns.
        parameters (dict | None): The parameters of the last query, or None before any.
    """

    def __init__(self, rows):
        """Holds the rows to return.

        Args:
            rows (list): The rows every query returns.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.parameters = None

    def execute(self, statement, parameters):
        """Records the parameters and returns the fixed rows.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The query, which is not run.
            parameters (dict): The query's parameters.

        Returns:
            list: The fixed rows.
        """
        self.parameters = parameters
        return self.rows


class ReadingSizesExample:
    """Reads the stand-in rows through the source and prints each contract's sizes.

    Attributes:
        source (StoxkartLotSizeSource): The source being read.
        connection (StandInConnection): The stand-in connection.
    """

    def __init__(self):
        """Builds the source and a connection holding the rows.

        Returns:
            None: This method returns nothing.
        """
        self.source = StoxkartLotSizeSource()
        self.connection = StandInConnection([
            types.SimpleNamespace(
                instrument_id='bse-usdinr-future-oct',
                units='1000',
            ),
            types.SimpleNamespace(
                instrument_id='ncdex-dhaniya-future-nov',
                units='5',
            ),
            types.SimpleNamespace(
                instrument_id='ncdex-jeera-future-nov',
                units='3',
            ),
        ])

    def run(self):
        """Prints the sizes read and the parameters the query was given.

        Returns:
            None: This method returns nothing.
        """
        sizes = self.source.read(
            self.connection,
            datetime.date(2026, 9, 28),
            [
                'bse_currency_futures',
                'ncdex_commodity_futures',
            ],
        )
        for instrument_id in sorted(sizes):
            texts = []
            for size in sorted(sizes[instrument_id]):
                texts.append(format(size, 'f'))
            print(f'{instrument_id}: {texts}')
        print(f'Broker queried: {self.connection.parameters["broker"]}')
        print(f'Mapping date: {self.connection.parameters["mapping_date"]}')
        print(f'Segments: {self.connection.parameters["segments"]}')
        print(f'Exchange labels: {self.connection.parameters["exchanges"]}')


if __name__ == '__main__':
    ReadingSizesExample().run()
