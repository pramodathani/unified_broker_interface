"""Tells a connection the broker's server reset from the network errors that are not resets, and shows what a broker that cannot read its order book does after one.

A reset is the one failure after which `BrokerOrders.send_place` reads the broker's order book to settle whether the order was placed: when the server resets or drops the connection, the request usually never reached it. A timeout is never treated that way, because a slow broker may still be working on the order. requests wraps the socket's own error, so `is_connection_reset` searches inside it.

A broker class that does not override `find_placed_order` cannot read its book, so `recover_after_reset` leaves the outcome `unknown` and only adds why. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/base/BrokerOrders/example_5_telling_a_reset_from_a_timeout.py
"""

import http.client

import requests
import urllib3.exceptions

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_answer import (
    BrokerAnswer,
)
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class ExampleBrokerOrders(BrokerOrders):
    """A made-up broker that cannot read its order book."""

    BROKER_NAME = 'example'


class TellingAResetFromATimeoutExample:
    """Classifies five network errors and settles one reset.

    Attributes:
        broker_orders (ExampleBrokerOrders): The made-up broker's order class.
    """

    def __init__(self):
        """Builds the order class.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleBrokerOrders()

    def run(self):
        """Prints whether each error is a reset, then what a reset becomes for this broker.

        Returns:
            None: This method returns nothing.
        """
        reset = requests.exceptions.ConnectionError(
            urllib3.exceptions.ProtocolError(
                'Connection aborted.',
                ConnectionResetError(104, 'Connection reset by peer'),
            ),
        )
        errors = [
            ('connection reset by peer', reset),
            (
                'closed without an answer',
                requests.exceptions.ConnectionError(
                    urllib3.exceptions.ProtocolError(
                        'Connection aborted.',
                        http.client.RemoteDisconnected('Remote end closed connection without response'),
                    ),
                ),
            ),
            ('read timeout', requests.exceptions.ReadTimeout('read timed out')),
            ('connect timeout', requests.exceptions.ConnectTimeout('connect timed out')),
            (
                'refused connection',
                requests.exceptions.ConnectionError(
                    urllib3.exceptions.NewConnectionError(None, 'Connection refused'),
                ),
            ),
        ]
        for label, error in errors:
            print(f'{label}: reset {self.broker_orders.is_connection_reset(error)}')
        answer = BrokerAnswer(0.0)
        answer.status_message = f'{type(reset).__name__}: {reset}'
        answer.connection_reset = True
        broker_request = BrokerRequest('POST', 'https://api.example.in/orders', {})
        settled = self.broker_orders.recover_after_reset(broker_request, answer, 0.0)
        print(f'Outcome after a reset: {settled.outcome}')
        print(f'Status message: {settled.status_message}')


if __name__ == '__main__':
    TellingAResetFromATimeoutExample().run()
