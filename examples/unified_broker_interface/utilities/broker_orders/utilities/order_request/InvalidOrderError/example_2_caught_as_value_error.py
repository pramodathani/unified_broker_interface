"""Shows that `InvalidOrderError` is a `ValueError`, so code that already handles bad values handles it too.

The error is raised here directly, as a caller's own validation might, and is caught once as `InvalidOrderError` and once as the broader `ValueError`. Its message is the text the order routes answer with.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/order_request/InvalidOrderError/example_2_caught_as_value_error.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)


class CaughtAsValueErrorExample:
    """Raises the error and catches it two ways."""

    def check_quantity(self, quantity):
        """Refuses a quantity below one.

        Args:
            quantity (int): The quantity to check.

        Returns:
            int: The quantity, when it is valid.

        Raises:
            InvalidOrderError: When the quantity is below one.
        """
        if quantity < 1:
            raise InvalidOrderError('quantity must be a whole number of at least 1')
        return quantity

    def run(self):
        """Raises the error twice and catches it as each type.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.check_quantity(0)
        except InvalidOrderError as error:
            print(f'Caught as InvalidOrderError: {error}')
        try:
            self.check_quantity(-5)
        except ValueError as error:
            print(f'Caught as ValueError: {type(error).__name__}: {error}')
        print(f'Valid quantity passes: {self.check_quantity(10)}')


if __name__ == '__main__':
    CaughtAsValueErrorExample().run()
