"""Shows `MarginCalculatorError` raised when a broker cannot be reached at all, and that it keeps the network error as its cause.

When the connection fails, `send_once` turns requests' exception into a `MarginCalculatorError` naming the broker, and keeps the original as `__cause__`, so a log line reads plainly while the details are still there. This program uses a stand-in session that fails the way a refused connection does, so nothing leaves the machine.

Notice that the error is a `MarginCalculatorError`, which the calibration catches, and not the `ConnectionError` it came from, which it would not.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/base/MarginCalculatorError/example_2_a_broker_that_cannot_be_reached.py
"""

import requests

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.dhan import (
    DhanMarginCalculator,
)


class UnreachableSession:
    """A session whose every request fails to connect."""

    def request(self, method, url, **options):
        """Fails to connect.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **options: The request's options.

        Returns:
            None: This method never returns.

        Raises:
            requests.ConnectionError: Always.
        """
        del method
        del options
        raise requests.ConnectionError(f'connection refused by {url}')


class ABrokerThatCannotBeReachedExample:
    """Sends one request to an unreachable Dhan.

    Attributes:
        calculator (DhanMarginCalculator): The calculator.
    """

    def __init__(self):
        """Builds the calculator.

        Returns:
            None: This method returns nothing.
        """
        login = {
            'access_token': 'stand-in-token',
        }
        settings = {
            'client_id': '1000000001',
        }
        self.calculator = DhanMarginCalculator(login, settings, UnreachableSession())

    def run(self):
        """Sends the request and prints the error and its cause.

        Returns:
            None: This method returns nothing.
        """
        request = BrokerRequest('POST', 'https://api.dhan.co/v2/margincalculator', {}, json_body={})
        try:
            self.calculator.send(request)
        except MarginCalculatorError as error:
            print(f'{type(error).__name__}: {error}')
            print(f'Caused by {type(error.__cause__).__name__}')


if __name__ == '__main__':
    ABrokerThatCannotBeReachedExample().run()
