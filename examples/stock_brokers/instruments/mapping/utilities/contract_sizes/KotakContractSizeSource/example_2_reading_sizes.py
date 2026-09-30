"""Reads Kotak's lot size converted to quotation units for a few contracts through a stand-in connection.

`read` runs the source's query and returns, for each contract, the set of distinct sizes its rows give, as decimals with trailing zeros removed. The stand-in rows hold the size as the database would compute it from that expression, including trailing zeros, which `read` normalises away. A negative figure, which a broken denominator could produce, is left out.

The connection is a small stand-in that returns the rows it was built with and records the parameters of the query, so the program needs no database. The parameters show that the query is limited to Kotak's rows on the trusted exchange labels.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/KotakContractSizeSource/example_2_reading_sizes.py
"""

import datetime
import types

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    KotakContractSizeSource,
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
        source (KotakContractSizeSource): The source being read.
        connection (StandInConnection): The stand-in connection.
    """

    def __init__(self):
        """Builds the source and a connection holding the rows.

        Returns:
            None: This method returns nothing.
        """
        self.source = KotakContractSizeSource()
        self.connection = StandInConnection([
            types.SimpleNamespace(
                instrument_id='gold-future-oct',
                units='100.0000',
            ),
            types.SimpleNamespace(
                instrument_id='usdinr-future-oct',
                units='1000.00',
            ),
            types.SimpleNamespace(
                instrument_id='silver-future-dec',
                units='30.000',
            ),
            types.SimpleNamespace(
                instrument_id='copper-future-oct',
                units='-1',
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
                'mcx_commodity_futures',
                'nse_currency_futures',
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
