"""Sends the order updates socket a mix of messages and shows which ones become orders.

Kite can batch several messages into one frame as a JSON list, and not every message is an order update. `ZerodhaOrderUpdatesSocket` hands on only the `order` entries of a frame, logs Kite's `error` messages as errors, logs any other message type as ignored, drops binary frames silently because they are market data it never subscribed to, and notes a frame that is not JSON at debug level.

No real socket is opened. The program registers a stand-in `websocket` package whose one connection delivers four frames: a JSON list holding an order update, an error and a `message` entry; a binary frame; a frame that is not JSON; and a second order update on its own. The session is a stand-in with fixed credentials, so no Kite login happens. The logger shows debug lines so the ignored frame appears.

Notice that the callback runs twice, once per frame that held an order, and that the binary frame leaves no trace at all.

Run it from the project root:

    python examples/stock_brokers/websockets/zerodha/ZerodhaOrderUpdatesSocket/example_2_errors_and_other_messages.py
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


class ErrorsAndOtherMessagesExample:
    """Runs the order updates socket against a mix of scripted frames.

    Attributes:
        socket (ZerodhaOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the frames, the stand-in package and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.DEBUG)
        batch = [
            {
                'type': 'order',
                'data': self.order('260925000000002', 'OPEN', 0),
            },
            {
                'type': 'error',
                'data': 'Too many requests',
            },
            {
                'type': 'message',
                'data': 'Welcome',
            },
        ]
        single = {
            'type': 'order',
            'data': self.order('260925000000002', 'COMPLETE', 5),
        }
        messages = [
            json.dumps(batch),
            b'\x00\x01\x00\x08binary',
            'not json',
            json.dumps(single),
        ]
        websocket_module = ScriptedWebsocketModule(messages)
        sys.modules['websocket'] = websocket_module
        self.socket = ZerodhaOrderUpdatesSocket(StandInSession(), self.print_orders, logging.getLogger('zerodha.orders'))
        websocket_module.when_finished = self.socket.close

    def order(self, order_id, status, filled_quantity):
        """A Kite order postback for a TCS sell.

        Args:
            order_id (str): Kite's order id.
            status (str): Kite's order status.
            filled_quantity (int): How much has filled.

        Returns:
            dict: The order.
        """
        return {
            'order_id': order_id,
            'status': status,
            'tradingsymbol': 'TCS',
            'exchange': 'NSE',
            'transaction_type': 'SELL',
            'quantity': 5,
            'filled_quantity': filled_quantity,
            'average_price': 4120.0,
        }

    def print_orders(self, orders, received_at):
        """Prints each order the socket handed on.

        Args:
            orders (list): Kite's orders from one message, exactly as sent.
            received_at (datetime.datetime): When the message arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        print(f'Callback received {len(orders)} order(s)')
        for order in orders:
            print(f"Order {order['order_id']} {order['status']}: {order['transaction_type']} {order['filled_quantity']} {order['tradingsymbol']} at {order['average_price']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    ErrorsAndOtherMessagesExample().run()
