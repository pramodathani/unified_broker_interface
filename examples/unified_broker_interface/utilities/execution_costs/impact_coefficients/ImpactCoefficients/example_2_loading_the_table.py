"""Loads `unified.impact_coefficients` as the table's file seeds it, from a stand-in database.

`load` reads every row on a cursor the caller opened and replaces whatever was held, so a long-running process can reload it. The stand-in database answers with the three seeded rows, all at the textbook 1.0 and none fitted, so no PostgreSQL is used.

Notice that every class reads as not fitted, which is how the table stays until real large orders exist to fit it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/impact_coefficients/ImpactCoefficients/example_2_loading_the_table.py
"""

import decimal

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.impact_coefficients import (
    ImpactCoefficients,
)


class LoadingTheTableExample:
    """Loads the seeded rows and prints them.

    Attributes:
        database (StandInExecutionDatabase): The stand-in database.
        coefficients (ImpactCoefficients): The coefficients, empty until loaded.
    """

    def __init__(self):
        """Builds the database with the seeded rows.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInExecutionDatabase()
        self.database.coefficient_rows = [
            ('securities', decimal.Decimal('1.0'), None),
            ('currency', decimal.Decimal('1.0'), None),
            ('commodity', decimal.Decimal('1.0'), None),
        ]
        self.coefficients = ImpactCoefficients()

    def run(self):
        """Loads and prints the rows.

        Returns:
            None: This method returns nothing.
        """
        print(f'Before loading: {self.coefficients.rows}')
        with self.database.connect().cursor() as cursor:
            count = self.coefficients.load(cursor)
        print(f'Rows loaded: {count}')
        for segment in ['nse_equities', 'bse_currency_options', 'mcx_commodity_options']:
            print(f'{segment}: {self.coefficients.coefficient(segment)}, fitted {self.coefficients.is_fitted(segment)}')


if __name__ == '__main__':
    LoadingTheTableExample().run()
