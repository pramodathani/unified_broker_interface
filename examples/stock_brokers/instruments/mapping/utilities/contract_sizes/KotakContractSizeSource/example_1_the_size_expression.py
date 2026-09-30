"""Prints the SQL expression Kotak's lot size converted to quotation units is read with, and the query around it.

Kotak counts GOLD in kilograms, so its lot size of 1 is multiplied by its general numerator and divided by its general denominator to reach the 100 units of 10 grams the exchange quotes in; on currencies it gives a multiplier as well, which scales the lot size when it is positive.

The program only builds the expression and the query text, so it needs no database. The query joins the date's broker mappings to the Kotak snapshot on the broker token and the download date, and keeps only the exchange labels this source is trusted on.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/KotakContractSizeSource/example_1_the_size_expression.py
"""

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    KotakContractSizeSource,
)


class ReadingTheExpressionExample:
    """Prints the source's settings, its size expression and its query.

    Attributes:
        source (KotakContractSizeSource): The source being shown.
    """

    def __init__(self):
        """Builds the source.

        Returns:
            None: This method returns nothing.
        """
        self.source = KotakContractSizeSource()

    def run(self):
        """Prints the name, the broker, the trusted exchange labels, the expression and the query.

        Returns:
            None: This method returns nothing.
        """
        print(f'Name: {self.source.NAME}')
        print(f'Broker: {self.source.BROKER}')
        print(f'Token column: {self.source.TOKEN_COLUMN}')
        print(f'Exchange column: {self.source.EXCHANGE_COLUMN}')
        print(f'Trusted exchange labels: {self.source.EXCHANGES}')
        print(f'Size expression: {self.source.units_expression()}')
        print('Query:')
        print(str(self.source.statement()))


if __name__ == '__main__':
    ReadingTheExpressionExample().run()
