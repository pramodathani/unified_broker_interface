"""Pings a stand-in broker that fails twice and then recovers, and shows that the warmer logs only the change, never each failure.

`ping` is the warmer's isolation point: it catches anything a ping raises, so a broker that cannot be reached never disturbs an order. It logs a warning when a broker starts failing and an information message when it works again, and stays quiet in between. The program calls `ping` directly five times, then calls `run` on the main thread, which the thread started by `start` would normally do.

The broker is a stand-in whose `warm_connection` raises `requests.ConnectionError` on a script of pings and sends nothing. On its eighth ping it sets the warmer's stop event, which ends `run`. After a failed ping `run` waits the whole `WARM_INTERVAL_SECONDS`, which is 0.05 seconds here, so the program finishes in well under a second.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_warmer/ConnectionWarmer/example_2_failing_and_recovering.py
"""

import requests

from unified_broker_interface.utilities.broker_orders.utilities.connection_warmer import (
    ConnectionWarmer,
)


class StandInAdapter:
    """A stand-in for the broker's adapter, holding only its pool size.

    Attributes:
        pool_size (int): How many connections the pool keeps.
    """

    def __init__(self, pool_size):
        """Builds the adapter.

        Args:
            pool_size (int): How many connections the pool keeps.

        Returns:
            None: This method returns nothing.
        """
        self.pool_size = pool_size


class FlakyBroker:
    """A stand-in for a `BrokerOrders` instance whose pings fail on a script.

    Attributes:
        BROKER_NAME (str): The broker's name.
        WARM_INTERVAL_SECONDS (float): How often each connection is pinged.
        adapter (StandInAdapter): The adapter holding the pool size.
        failing_pings (list): The ping numbers that raise.
        ping_limit (int): The ping on which the warmer is stopped.
        pings (int): How many pings arrived.
        stop_event (threading.Event | None): The warmer's stop event.
    """

    BROKER_NAME = 'dhan'
    WARM_INTERVAL_SECONDS = 0.05

    def __init__(self, failing_pings, ping_limit):
        """Builds the stand-in.

        Args:
            failing_pings (list): The ping numbers that raise.
            ping_limit (int): The ping on which the warmer is stopped.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = StandInAdapter(1)
        self.failing_pings = failing_pings
        self.ping_limit = ping_limit
        self.pings = 0
        self.stop_event = None

    def warm_connection(self):
        """Records one ping, raising on the scripted ones and stopping the warmer on the last.

        Returns:
            str: `kept` when the ping succeeds.

        Raises:
            requests.ConnectionError: On a scripted failing ping.
        """
        self.pings = self.pings + 1
        if self.pings >= self.ping_limit:
            self.stop_event.set()
        if self.pings in self.failing_pings:
            raise requests.ConnectionError('Max retries exceeded with url: /')
        return 'kept'


class PrintingLogger:
    """A stand-in for `logging.Logger` that prints each message with its level."""

    def warning(self, message, *arguments):
        """Prints a warning.

        Args:
            message (str): The format string.
            *arguments (object): The values for it.

        Returns:
            None: This method returns nothing.
        """
        print(f'    WARNING {message % arguments}')

    def info(self, message, *arguments):
        """Prints an information message.

        Args:
            message (str): The format string.
            *arguments (object): The values for it.

        Returns:
            None: This method returns nothing.
        """
        print(f'    INFO {message % arguments}')


class FailingAndRecoveringExample:
    """Pings a flaky broker by hand, then lets `run` ping it until it is stopped.

    Attributes:
        broker (FlakyBroker): The broker being warmed.
        warmer (ConnectionWarmer): The warmer.
    """

    def __init__(self):
        """Builds a warmer for a broker failing on pings 2, 3 and 6, stopped on ping 8.

        Returns:
            None: This method returns nothing.
        """
        failing_pings = [
            2,
            3,
            6,
        ]
        self.broker = FlakyBroker(failing_pings, 8)
        self.warmer = ConnectionWarmer(self.broker, PrintingLogger())
        self.broker.stop_event = self.warmer.stop_event

    def run(self):
        """Pings five times by hand, then runs the loop until the broker stops it.

        Returns:
            None: This method returns nothing.
        """
        for _ in range(5):
            print(f'Ping {self.warmer.pings + 1}:')
            answered = self.warmer.ping()
            print(f'    answered={answered}, failing={self.warmer.failing}')
        print('Running the loop on this thread:')
        self.warmer.run()
        print(f'Pings attempted: {self.warmer.pings}, failures: {self.warmer.failures}')


if __name__ == '__main__':
    FailingAndRecoveringExample().run()
