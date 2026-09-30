"""Reads a source's rows and shows which sizes it keeps, and what the bare base class does.

`read` runs the source's query on an open connection and gathers, for each contract, the set of distinct sizes its rows give. A row whose size is missing, zero or negative is left out, and a contract listed twice with two different sizes keeps both, which is how the resolver later notices a source contradicting itself.

The connection here is a small stand-in that returns five made-up rows and remembers the parameters it was given, so the program needs no database. The rows copy a case seen in Stoxkart's file on 2026-09-28, where one USDINR option was listed with lots of 1000 and 2000.

The base class names no expression of its own, so calling `units_expression` on it raises `NotImplementedError`; the program catches that to show it.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeSource/example_2_reading_rows_that_disagree.py
"""

import datetime
import types

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeSource,
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


class ReadingRowsThatDisagreeExample:
    """Reads five stand-in rows through Stoxkart's source and tries the base class's expression.

    Attributes:
        source (StoxkartLotSizeSource): The source being read.
        connection (StandInConnection): The stand-in connection.
    """

    def __init__(self):
        """Builds the source and a connection holding five rows.

        Returns:
            None: This method returns nothing.
        """
        self.source = StoxkartLotSizeSource()
        self.connection = StandInConnection([
            types.SimpleNamespace(
                instrument_id='usdinr-option',
                units='1000',
            ),
            types.SimpleNamespace(
                instrument_id='usdinr-option',
                units='2000',
            ),
            types.SimpleNamespace(
                instrument_id='eurinr-future',
                units='1000.00',
            ),
            types.SimpleNamespace(
                instrument_id='gbpinr-future',
                units=None,
            ),
            types.SimpleNamespace(
                instrument_id='jpyinr-future',
                units='0',
            ),
        ])

    def run(self):
        """Prints the sizes read, the query parameters and the base class's refusal.

        Returns:
            None: This method returns nothing.
        """
        sizes = self.source.read(
            self.connection,
            datetime.date(2026, 9, 28),
            [
                'nse_currency_options',
                'nse_currency_futures',
            ],
        )
        for instrument_id in sorted(sizes):
            texts = []
            for size in sorted(sizes[instrument_id]):
                texts.append(format(size, 'f'))
            print(f'{instrument_id}: {texts}')
        print(f'Broker queried: {self.connection.parameters["broker"]}')
        print(f'Exchange labels queried: {self.connection.parameters["exchanges"]}')
        base_source = ContractSizeSource()
        try:
            base_source.units_expression()
        except NotImplementedError:
            print('The base class has no size expression of its own.')


if __name__ == '__main__':
    ReadingRowsThatDisagreeExample().run()
