"""Runs the underlyings command line with a date written the wrong way round, and shows that it stops before touching the database.

`UnderlyingCommand.run` reads its arguments from `sys.argv`, as `python -m stock_brokers.instruments.mapping.utilities.underlyings --date 2026-09-28` would pass them. A `--date` that is not `YYYY-MM-DD` is refused with a message and exit code 2, which the project uses for a bad argument, and no resolver or database engine is built.

The program sets `sys.argv` itself to the date `28-09-2026`, so it needs no database and no shell arguments.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/underlyings/UnderlyingCommand/example_1_a_malformed_date.py
"""

import sys

from stock_brokers.instruments.mapping.utilities.underlyings import (
    UnderlyingCommand,
)


class MalformedDateExample:
    """Runs the command with a day-first date and prints its exit code.

    Attributes:
        command (UnderlyingCommand): The command being shown.
    """

    def __init__(self):
        """Builds the command and sets the arguments it will read.

        Returns:
            None: This method returns nothing.
        """
        sys.argv = [
            'underlyings',
            '--date',
            '28-09-2026',
            '--dry-run',
        ]
        self.command = UnderlyingCommand()

    def run(self):
        """Runs the command and prints the exit code it returns.

        Returns:
            None: This method returns nothing.
        """
        exit_code = self.command.run()
        print(f'Exit code: {exit_code}')


if __name__ == '__main__':
    MalformedDateExample().run()
