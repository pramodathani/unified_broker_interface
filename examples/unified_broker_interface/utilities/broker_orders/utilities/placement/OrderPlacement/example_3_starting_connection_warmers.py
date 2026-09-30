"""Starts connection warmers for the brokers the configuration names, with every ping caught by a stand-in so nothing reaches a broker.

`warm_broker_names` reads `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS`, where `all` means every broker. `start_connection_warmers` starts one `ConnectionWarmer` thread per named broker; a name that is not a broker is logged and ignored, because warming only saves time and must never stop the order engine from starting.

A real warmer sends a `HEAD` request to the broker's host through the order class's adapter. Here Zerodha's adapter is replaced with a stand-in whose `send` records the URL and returns a response with no connection, which the order class reads as a connection to discard; nothing leaves the machine. The program waits for the first ping, then stops the warmer. The configuration is set in the loaded settings rather than in `.env`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/placement/OrderPlacement/example_3_starting_connection_warmers.py
"""

import threading

from unified_broker_interface.utilities.broker_orders.utilities.placement import (
    OrderPlacement,
)
from utilities.configurations import api_configuration


class EmptyRawResponse:
    """A stand-in for a urllib3 response whose connection is already gone.

    Attributes:
        connection (None): No connection, so the ping's connection is discarded.
    """

    def __init__(self):
        """Builds the response.

        Returns:
            None: This method returns nothing.
        """
        self.connection = None

    def release_conn(self):
        """Does nothing, as there is no connection to return.

        Returns:
            None: This method returns nothing.
        """
        return None


class StandInResponse:
    """A stand-in for a `requests.Response` carrying only its raw response.

    Attributes:
        raw (EmptyRawResponse): The raw response.
    """

    def __init__(self):
        """Builds the response.

        Returns:
            None: This method returns nothing.
        """
        self.raw = EmptyRawResponse()


class RecordingAdapter:
    """A stand-in for `IdleLimitedAdapter` that records each ping instead of sending it.

    Attributes:
        pool_size (int): How many connections the pool keeps.
        pinged_urls (list): The URL of each ping.
        first_ping (threading.Event): Set when the first ping arrives.
    """

    def __init__(self):
        """Builds the adapter.

        Returns:
            None: This method returns nothing.
        """
        self.pool_size = 1
        self.pinged_urls = []
        self.first_ping = threading.Event()

    def send(self, prepared_request, **keyword_arguments):
        """Records the ping and returns a response with no connection.

        Args:
            prepared_request (requests.PreparedRequest): The ping.
            **keyword_arguments (object): The stream, timeout and certificate settings.

        Returns:
            StandInResponse: The response.
        """
        self.pinged_urls.append(f'{prepared_request.method} {prepared_request.url}')
        self.first_ping.set()
        return StandInResponse()


class RecordingLogger:
    """A stand-in for `logging.Logger` that keeps each message.

    Attributes:
        messages (list): The messages logged, with their levels.
    """

    def __init__(self):
        """Builds the logger.

        Returns:
            None: This method returns nothing.
        """
        self.messages = []

    def warning(self, message, *arguments):
        """Keeps a warning.

        Args:
            message (str): The format string.
            *arguments (object): The values for it.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append('WARNING ' + message % arguments)

    def info(self, message, *arguments):
        """Keeps an information message.

        Args:
            message (str): The format string.
            *arguments (object): The values for it.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append('INFO ' + message % arguments)

    def exception(self, message, *arguments):
        """Keeps an error message.

        Args:
            message (str): The format string.
            *arguments (object): The values for it.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append('ERROR ' + message % arguments)


class StartingConnectionWarmersExample:
    """Starts warmers for Zerodha and a misspelt broker, and stops them.

    Attributes:
        logger (RecordingLogger): Where the placement logs.
        placement (OrderPlacement): The placement.
        adapter (RecordingAdapter): Zerodha's stand-in adapter.
    """

    def __init__(self):
        """Configures warming and builds the placement with Zerodha's stand-in adapter.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_broker_priority'] = []
        api_configuration['order_warm_brokers'] = [
            'all',
        ]
        self.logger = RecordingLogger()
        self.placement = OrderPlacement(self.logger, 1)
        self.adapter = RecordingAdapter()
        self.placement.broker_orders['zerodha'].adapter = self.adapter

    def run(self):
        """Prints the warmed names under two settings, starts the warmers and stops them.

        Returns:
            None: This method returns nothing.
        """
        print(f'With all: {self.placement.warm_broker_names()}')
        api_configuration['order_warm_brokers'] = [
            'zerodha',
            'zerodah',
            '',
        ]
        print(f'With a list: {self.placement.warm_broker_names()}')
        self.placement.start_connection_warmers()
        self.adapter.first_ping.wait(5)
        for warmer in self.placement.connection_warmers:
            warmer.stop()
        print(f'Warmers started: {len(self.placement.connection_warmers)}')
        for warmer in self.placement.connection_warmers:
            print(f'  {warmer.broker_orders.BROKER_NAME}: running after stop {warmer.is_running()}, failures {warmer.failures}')
        print(f'First ping: {self.adapter.pinged_urls[0]}')
        print(f'Logged: {self.logger.messages}')


if __name__ == '__main__':
    StartingConnectionWarmersExample().run()
