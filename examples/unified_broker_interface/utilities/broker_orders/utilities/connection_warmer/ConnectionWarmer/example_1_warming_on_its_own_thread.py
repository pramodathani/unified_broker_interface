"""Starts a `ConnectionWarmer` on its own thread, lets it ping a stand-in broker a fixed number of times, and stops it.

A new TLS connection to a broker costs a handshake, which an order should not have to wait for. The warmer keeps every pooled connection freshly used by pinging them one at a time on a daemon thread. Its first round pings once per connection back to back, to open them all; after that it spaces pings `WARM_INTERVAL_SECONDS` divided by the pool size apart.

The broker here is a stand-in with the attributes the warmer reads: `BROKER_NAME`, `WARM_INTERVAL_SECONDS`, `adapter.pool_size` and `warm_connection`. Its `warm_connection` sends nothing; it records the ping and, on the fifth, sets the warmer's stop event, so the thread always stops after exactly five pings. The interval is 0.1 seconds and the pool holds two connections, so the whole run takes about a fifth of a second.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/connection_warmer/ConnectionWarmer/example_1_warming_on_its_own_thread.py
"""

import threading

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


class StandInBroker:
    """A stand-in for a `BrokerOrders` instance whose pings are recorded rather than sent.

    Attributes:
        BROKER_NAME (str): The broker's name.
        WARM_INTERVAL_SECONDS (float): How often each connection is pinged.
        adapter (StandInAdapter): The adapter holding the pool size.
        ping_limit (int): The ping on which the warmer is stopped.
        pings (int): How many pings arrived.
        stop_event (threading.Event | None): The warmer's stop event, set on the last ping.
        finished (threading.Event): Set when the last ping arrives.
    """

    BROKER_NAME = 'zerodha'
    WARM_INTERVAL_SECONDS = 0.1

    def __init__(self, ping_limit):
        """Builds the stand-in.

        Args:
            ping_limit (int): The ping on which the warmer is stopped.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = StandInAdapter(2)
        self.ping_limit = ping_limit
        self.pings = 0
        self.stop_event = None
        self.finished = threading.Event()

    def warm_connection(self):
        """Records one ping and stops the warmer on the last one.

        Returns:
            str: Always `kept`.
        """
        self.pings = self.pings + 1
        if self.pings >= self.ping_limit:
            self.stop_event.set()
            self.finished.set()
        return 'kept'


class SilentLogger:
    """A stand-in for `logging.Logger` that keeps each message.

    Attributes:
        messages (list): The messages logged.
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
        self.messages.append(message % arguments)

    def info(self, message, *arguments):
        """Keeps an information message.

        Args:
            message (str): The format string.
            *arguments (object): The values for it.

        Returns:
            None: This method returns nothing.
        """
        self.messages.append(message % arguments)


class WarmingOnItsOwnThreadExample:
    """Runs the warmer on its thread until the stand-in stops it.

    Attributes:
        broker (StandInBroker): The broker being warmed.
        logger (SilentLogger): Where the warmer logs.
        warmer (ConnectionWarmer): The warmer.
    """

    def __init__(self):
        """Builds the warmer for a stand-in that stops it on the fifth ping.

        Returns:
            None: This method returns nothing.
        """
        self.broker = StandInBroker(5)
        self.logger = SilentLogger()
        self.warmer = ConnectionWarmer(self.broker, self.logger)
        self.broker.stop_event = self.warmer.stop_event

    def run(self):
        """Starts the warmer, waits for the fifth ping, stops it and prints what happened.

        Returns:
            None: This method returns nothing.
        """
        print(f'Running before start: {self.warmer.is_running()}')
        self.warmer.start()
        self.warmer.start()
        self.broker.finished.wait(5)
        self.warmer.stop()
        print(f'Thread name: {self.warmer.thread.name}')
        print(f'Running after stop: {self.warmer.is_running()}')
        print(f'Pings attempted: {self.warmer.pings}, failures: {self.warmer.failures}, failing now: {self.warmer.failing}')
        print(f'Pings the broker saw: {self.broker.pings}')
        print(f'Messages logged: {self.logger.messages}')


if __name__ == '__main__':
    WarmingOnItsOwnThreadExample().run()
