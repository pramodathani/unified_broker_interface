"""Writes a new contract size source by subclassing `ContractSizeSource` and prints the query it builds.

A source names one broker, the snapshot columns holding its token and exchange label, the exchange labels it is trusted on, and an SQL expression for the size in quotation units. This program invents a source that reads Dhan's `lot_size` column on MCX, which is not one of the project's sources, to show how little a subclass has to say.

`numeric` wraps a snapshot column in a guard that turns anything that is not a number into null, so a broker file holding text in a numeric column cannot break the query. `statement` then joins the date's broker mappings to the broker's raw snapshot on the token and the download date, and keeps only live contracts in the requested segments on the trusted exchange labels. Nothing is executed here, so no database is needed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeSource/example_1_writing_a_new_source.py
"""

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeSource,
)


class DhanLotSizeSource(ContractSizeSource):
    """An illustrative source reading Dhan's `lot_size` column on MCX."""

    NAME = 'dhan_lot_size'
    BROKER = 'dhan'
    TOKEN_COLUMN = 'security_id'
    EXCHANGE_COLUMN = 'exch_id'
    EXCHANGES = [
        'MCX',
    ]

    def units_expression(self):
        """The `lot_size` column, read as a number.

        Returns:
            str: The SQL expression.
        """
        return self.numeric('lot_size')


class WritingANewSourceExample:
    """Builds the illustrative source and prints its settings, its expressions and its query.

    Attributes:
        source (DhanLotSizeSource): The source being shown.
    """

    def __init__(self):
        """Builds the source.

        Returns:
            None: This method returns nothing.
        """
        self.source = DhanLotSizeSource()

    def run(self):
        """Prints the source's settings, the numeric guard, the size expression and the full query.

        Returns:
            None: This method returns nothing.
        """
        print(f'Name: {self.source.NAME}')
        print(f'Broker: {self.source.BROKER}')
        print(f'Trusted exchange labels: {self.source.EXCHANGES}')
        print(f'Numeric guard on multiplier: {self.source.numeric("multiplier")}')
        print(f'Size expression: {self.source.units_expression()}')
        print('Query:')
        print(str(self.source.statement()))


if __name__ == '__main__':
    WritingANewSourceExample().run()
