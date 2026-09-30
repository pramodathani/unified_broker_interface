"""Receives one Kite order update on the order updates socket and prints the order it hands on.

Kite has no separate order endpoint. `ZerodhaOrderUpdatesSocket` connects to the same ticker as the quotes socket but subscribes to nothing, so the only messages it receives are `{"type": "order", "data": {...}}` updates, whose data is the same object as an order book row. The socket hands each message's orders, exactly as Kite sent them, to the function it was given, together with the moment the message arrived.

No real socket is opened. The program registers a stand-in `websocket` package whose one connection opens, delivers a single order update for a completed INFY buy, and closes; the stand-in then closes the socket, which ends `run_forever`. The session is a stand-in with fixed credentials, so no Kite login happens. The arrival time is not printed, because it is the wall clock.

Notice that the socket sends nothing when it opens and that the order reaches the callback unchanged.

Run it from the project root:

    python examples/stock_brokers/websockets/zerodha/ZerodhaOrderUpdatesSocket/example_1_receiving_an_order_update.py
"""

import json
import logging
import sys

from stock_brokers.websockets.zerodha import (
    ZerodhaOrderUpdatesSocket,
)


class StandInSession:
    """A stand-in for `ZerodhaSession` that answers with fixed credentials and never logs in."""

    def credentials(self):
        """The api key and access token the socket puts in the feed URL.

        Returns:
            tuple: The api key and the access token.
        """
        return (
            'kite-api-key',
            'kite-access-token',
        )

    def log_in_again(self, stale_token):
        """Reports a login request, which this program never expects.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.
        """
        print(f'Asked to log in again after {stale_token}')


class ScriptedConnection:
    """A stand-in for `websocket.WebSocketApp` that plays scripted messages to the socket's handlers.

    Attributes:
        url (str): The URL the socket asked for.
        messages (list): The messages to deliver after the connection opens.
        handlers (dict): The socket's callbacks, by name.
        when_finished (callable): Called after the last message, to close the socket.
    """

    def __init__(self, url, messages, handlers, when_finished):
        """Keeps what the socket passed in.

        Args:
            url (str): The URL the socket asked for.
            messages (list): The messages to deliver after the connection opens.
            handlers (dict): The socket's callbacks, by name.
            when_finished (callable): Called after the last message, to close the socket.

        Returns:
            None: This method returns nothing.
        """
        self.url = url
        self.messages = messages
        self.handlers = handlers
        self.when_finished = when_finished

    def run_forever(self, **options):
        """Opens, delivers every message, then closes, as a real connection would.

        Args:
            **options (dict): The ping settings the socket asks for.

        Returns:
            None: This method returns nothing.
        """
        print(f'Connecting to {self.url}')
        self.handlers['on_open'](self)
        for message in self.messages:
            self.handlers['on_message'](self, message)
        self.handlers['on_close'](self, 1000, 'normal closure')
        self.when_finished()

    def send(self, data):
        """Prints a message the socket sends to Kite.

        Args:
            data (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'Sent: {data}')

    def close(self):
        """Accepts the socket's request to close.

        Returns:
            None: This method returns nothing.
        """


class ScriptedWebsocketModule:
    """A stand-in for the `websocket` package that hands out one scripted connection.

    Attributes:
        messages (list): The messages the connection delivers.
        when_finished (callable | None): Called when the connection has delivered everything.
    """

    def __init__(self, messages):
        """Keeps the messages to deliver.

        Args:
            messages (list): The messages the connection delivers.

        Returns:
            None: This method returns nothing.
        """
        self.messages = messages
        self.when_finished = None

    def WebSocketApp(self, url, **handlers):
        """Builds the scripted connection, with the same signature as the real class.

        Args:
            url (str): The feed URL.
            **handlers (dict): The socket's `on_open`, `on_message`, `on_error` and `on_close` callbacks.

        Returns:
            ScriptedConnection: The connection.
        """
        return ScriptedConnection(url, self.messages, handlers, self.when_finished)


class ReceivingAnOrderUpdateExample:
    """Runs the order updates socket against one scripted order update.

    Attributes:
        socket (ZerodhaOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the order update, the stand-in package and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        order = {
            'order_id': '260925000000001',
            'exchange_order_id': '1100000012345678',
            'status': 'COMPLETE',
            'tradingsymbol': 'INFY',
            'exchange': 'NSE',
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'product': 'CNC',
            'quantity': 10,
            'filled_quantity': 10,
            'price': 1500.0,
            'average_price': 1499.5,
            'order_timestamp': '2026-09-25 10:15:30',
        }
        update = {
            'type': 'order',
            'data': order,
        }
        messages = [
            json.dumps(update),
        ]
        websocket_module = ScriptedWebsocketModule(messages)
        sys.modules['websocket'] = websocket_module
        self.socket = ZerodhaOrderUpdatesSocket(StandInSession(), self.print_orders, logging.getLogger('zerodha.orders'))
        websocket_module.when_finished = self.socket.close

    def print_orders(self, orders, received_at):
        """Prints each order the socket handed on.

        Args:
            orders (list): Kite's orders from one message, exactly as sent.
            received_at (datetime.datetime): When the message arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        for order in orders:
            print(f"Order {order['order_id']} {order['status']}: {order['transaction_type']} {order['filled_quantity']} {order['tradingsymbol']} at {order['average_price']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        print(f'Socket name: {self.socket.name}')
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    ReceivingAnOrderUpdateExample().run()
