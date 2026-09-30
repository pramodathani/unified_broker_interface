"""Writes a tiny socket on top of `BrokerWebsocket` and watches its reconnect loop.

`BrokerWebsocket` is the loop every broker's socket shares: connect and block until the connection closes, wait with a doubling backoff, and connect again, until `close` is called. A broker's subclass supplies `_connect`, which opens the connection, sets `_opened` when it opens and blocks until it closes, and `_log_in_again`, which the loop calls when the broker refuses the credentials.

This program's `ScriptedFeedSocket` is such a subclass. Its `_connect` opens nothing real: it takes the next line of a script, prints what the pretend connection did, and returns. The first connection opens and then drops, the second fails before opening, and the third opens and the program closes the socket from inside it, the way a script's signal handler would. The backoff is set to zero seconds so the program does not wait.

Notice that the loop logs a reconnect after each ended connection, that a connection that opened resets the backoff, and that `close` ends `run_forever` with `gave_up` still False.

Run it from the project root:

    python examples/stock_brokers/websockets/base/BrokerWebsocket/example_1_reconnecting_after_a_drop.py
"""

import logging
import sys

from stock_brokers.websockets.base import (
    BrokerWebsocket,
)


class ScriptedFeedSocket(BrokerWebsocket):
    """A socket whose connections follow a fixed script instead of reaching a broker.

    Attributes:
        script (list): What each connection does: `drop`, `fail` or `close`.
    """

    def __init__(self, script, logger):
        """Sets up the socket with its script.

        Args:
            script (list): What each connection does: `drop`, `fail` or `close`.
            logger (logging.Logger): Where the socket reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__('Scripted feed', logger)
        self.script = script

    def _connect(self):
        """Plays the next step of the script as one connection.

        Returns:
            None: This method returns nothing.

        Raises:
            ConnectionError: When the step is `fail`.
        """
        step = self.script.pop(0)
        if step == 'fail':
            raise ConnectionError('network unreachable')
        self._opened = True
        print('Connection opened.')
        if step == 'close':
            self.close()
        print('Connection ended.')

    def _log_in_again(self):
        """Reports a login, which this script never asks for.

        Returns:
            None: This method returns nothing.
        """
        print('Logging in again.')


class ReconnectingAfterADropExample:
    """Runs the scripted socket through a drop, a failure and a close.

    Attributes:
        socket (ScriptedFeedSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the socket with a zero second backoff.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        script = [
            'drop',
            'fail',
            'close',
        ]
        self.socket = ScriptedFeedSocket(script, logging.getLogger('feed'))
        self.socket.MIN_BACKOFF_SECONDS = 0

    def run(self):
        """Runs the reconnect loop until the script closes the socket.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    ReconnectingAfterADropExample().run()
