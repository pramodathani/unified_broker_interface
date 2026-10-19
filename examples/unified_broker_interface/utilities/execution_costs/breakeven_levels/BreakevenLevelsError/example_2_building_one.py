"""Builds a `BreakevenLevelsError` by hand and shows what the route makes of it.

The error carries a message and an HTTP status, and the instruments route answers `{"error": message}` with that status. This program raises one for a broker with no cost row and catches it.

Notice that it is an ordinary exception, so `str` gives the message too.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/breakeven_levels/BreakevenLevelsError/example_2_building_one.py
"""

from unified_broker_interface.utilities.execution_costs.breakeven_levels import (
    BreakevenLevelsError,
)


class BuildingOneExample:
    """Raises and catches one error."""

    def run(self):
        """Raises, catches and prints the error.

        Returns:
            None: This method returns nothing.
        """
        try:
            raise BreakevenLevelsError('The brokerage of nobody is not known; add a row to unified.broker_order_costs.', 409)
        except BreakevenLevelsError as error:
            print(f'Status: {error.status}')
            print(f'Answer: {{"error": "{error.message}"}}')
            print(f'As text: {error}')


if __name__ == '__main__':
    BuildingOneExample().run()
