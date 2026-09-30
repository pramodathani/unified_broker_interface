"""Shows `BrokerWebsocket` logging in again once after a refusal and giving up when refused again.

When a broker refuses the credentials, the subclass sets `_authentication_rejected` and returns from `_connect`. The shared loop then calls `_log_in_again` once and connects again. If that next connection is refused too, the loop decides the login did not help: it sets `gave_up`, logs that it is giving up, and returns from `run_forever`, so the broker's script can exit 1 and let systemd restart it. Separately, `close` can be called before the loop even starts, and then `run_forever` returns without connecting.

This program's `RefusingFeedSocket` subclasses `BrokerWebsocket` and refuses every connection, so no broker is reached. The backoff is set to zero seconds so the program does not wait. A second socket is closed before it runs to show the early return.

Notice the single login between the two refusals, and that the closed socket never prints a connection attempt.

Run it from the project root:

    python examples/stock_brokers/websockets/base/BrokerWebsocket/example_2_giving_up_after_a_second_refusal.py
"""

import logging
import sys

from stock_brokers.websockets.base import (
    BrokerWebsocket,
)


class RefusingFeedSocket(BrokerWebsocket):
    """A socket whose every connection is refused by the pretend broker.

    Attributes:
        attempts (int): How many connections have been tried.
        logins (int): How many times the socket logged in again.
    """

    def __init__(self, name, logger):
        """Sets up the socket.

        Args:
            name (str): The socket's name.
            logger (logging.Logger): Where the socket reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self.attempts = 0
        self.logins = 0

    def _connect(self):
        """Tries one connection, which the pretend broker refuses.

        Returns:
            None: This method returns nothing.
        """
        self.attempts = self.attempts + 1
        print(f'{self.name}: connection {self.attempts} refused with HTTP 401.')
        self._authentication_rejected = True

    def _log_in_again(self):
        """Pretends to log in again.

        Returns:
            None: This method returns nothing.
        """
        self.logins = self.logins + 1
        print(f'{self.name}: logged in again.')


class GivingUpAfterASecondRefusalExample:
    """Runs one socket until it gives up and another that was closed before it started.

    Attributes:
        refused_socket (RefusingFeedSocket): The socket that is refused twice.
        closed_socket (RefusingFeedSocket): The socket closed before it runs.
    """

    def __init__(self):
        """Builds both sockets with a zero second backoff.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        logger = logging.getLogger('feed')
        self.refused_socket = RefusingFeedSocket('Refused feed', logger)
        self.refused_socket.MIN_BACKOFF_SECONDS = 0
        self.closed_socket = RefusingFeedSocket('Closed feed', logger)

    def run(self):
        """Runs both sockets and prints how each one ended.

        Returns:
            None: This method returns nothing.
        """
        self.refused_socket.run_forever()
        print(f'Refused feed gave up: {self.refused_socket.gave_up} after {self.refused_socket.attempts} connections and {self.refused_socket.logins} login')
        self.closed_socket.close()
        self.closed_socket.run_forever()
        print(f'Closed feed gave up: {self.closed_socket.gave_up} after {self.closed_socket.attempts} connections')


if __name__ == '__main__':
    GivingUpAfterASecondRefusalExample().run()
