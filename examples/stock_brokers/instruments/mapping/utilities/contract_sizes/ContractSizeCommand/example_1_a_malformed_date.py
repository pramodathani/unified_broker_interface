"""Runs the contract size command line with a date it cannot read, and shows that it stops before touching the database.

`ContractSizeCommand.run` reads its arguments from `sys.argv`, as `python -m stock_brokers.instruments.mapping.utilities.contract_sizes --date 2026-09-15` would pass them. A `--date` that is not a real `YYYY-MM-DD` date is refused with a message and exit code 2, which the project uses for a bad argument, and no resolver or database engine is built.

The program sets `sys.argv` itself to the date `2026-09-31`, a day September does not have, so it needs no database and no shell arguments.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeCommand/example_1_a_malformed_date.py
"""

import sys

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeCommand,
)


class MalformedDateExample:
    """Runs the command with an impossible date and prints its exit code.

    Attributes:
        command (ContractSizeCommand): The command being shown.
    """

    def __init__(self):
        """Builds the command and sets the arguments it will read.

        Returns:
            None: This method returns nothing.
        """
        sys.argv = [
            'contract_sizes',
            '--date',
            '2026-09-31',
        ]
        self.command = ContractSizeCommand()

    def run(self):
        """Runs the command and prints the exit code it returns.

        Returns:
            None: This method returns nothing.
        """
        exit_code = self.command.run()
        print(f'Exit code: {exit_code}')


if __name__ == '__main__':
    MalformedDateExample().run()
