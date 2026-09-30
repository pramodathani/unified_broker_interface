"""Receives orders and positions on Fyers' order update socket and prints what it hands on.

`FyersOrderUpdatesSocket` connects to `wss://socket.fyers.in/trade/v3` with an `authorization` header of the app id and the access token, so a bad credential fails the handshake itself. Once open it subscribes to orders and positions, Fyers confirms with code 1605, and every change then arrives as `{"s": "ok", "orders": {...}}` or `{"s": "ok", "positions": {...}}`. Fyers answers the keepalive with a bare `ping` or `pong`, which the socket ignores.

This program scripts one connection delivering the subscription confirmation, a `pong`, a pending order, a position and the same order filled. No real socket is opened: a stand-in `websocket` package plays the frames and prints the handshake header names and what the socket sends, and a stand-in `stock_brokers.api.fyers` module issues a JWT token and serves the profile so the real `FyersSession` runs unchanged.

Notice that the callback receives orders and positions separately, and that the confirmation is logged rather than handed on.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersOrderUpdatesSocket/example_1_orders_and_positions.py
"""

import base64
import json
import logging
import sys
import types

from stock_brokers.websockets.fyers import (
    FyersOrderUpdatesSocket,
    FyersSession,
)


class LoginRecord:
    """The Fyers login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
        expired_logins (set): The login numbers whose token has already expired.
        refused_profiles (set): The login numbers whose session the profile endpoint refuses.
    """

    access_token = None
    login_count = 0
    expired_logins = set()
    refused_profiles = set()


class StandInFyersAPI:
    """A stand-in for `FyersAPI` whose construction is a pretend login that issues a JWT access token."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        expiry = 4102444800
        if LoginRecord.login_count in LoginRecord.expired_logins:
            expiry = 1
        claims = {
            'exp': expiry,
            'hsm_key': f'hsm-key-{LoginRecord.login_count}',
        }
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        LoginRecord.access_token = f'header.{payload}.signature'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'app_id': 'XY1234-100',
        }

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
        }

    def get(self, url, timeout):
        """Answers the profile call the session confirms every login with.

        Args:
            url (str): The endpoint the session calls.
            timeout (int): The request timeout in seconds.

        Returns:
            dict: What the real class returns, with Fyers' answer under `data`.
        """
        if LoginRecord.login_count in LoginRecord.refused_profiles:
            print(f'Profile refused for login {LoginRecord.login_count}')
            return {
                'data': {
                    's': 'error',
                    'code': -16,
                    'message': 'Could not authenticate the user',
                },
            }
        print(f'Profile served for login {LoginRecord.login_count}')
        return {
            'data': {
                's': 'ok',
                'data': {
                    'fy_id': 'XY01234',
                },
            },
        }


class HandshakeRefused(Exception):
    """A refused websocket handshake, carrying the HTTP status the way `websocket-client` does.

    Attributes:
        status_code (int): The HTTP status the broker answered with.
    """

    def __init__(self, status_code):
        """Keeps the status.

        Args:
            status_code (int): The HTTP status the broker answered with.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(f'Handshake status {status_code}')
        self.status_code = status_code


class ScriptedConnection:
    """A stand-in for `websocket.WebSocketApp` that either refuses the handshake or plays frames to the socket's handlers.

    Attributes:
        url (str): The URL the socket asked for.
        plan (dict): Either a `refuse_with` status or a list of `frames`.
        handlers (dict): The socket's callbacks, by name.
        closed (bool): Whether the socket asked to close, after which no more frames are delivered.
    """

    def __init__(self, url, plan, handlers):
        """Keeps what the socket passed in.

        Args:
            url (str): The URL the socket asked for.
            plan (dict): Either a `refuse_with` status or a list of `frames`.
            handlers (dict): The socket's callbacks, by name.

        Returns:
            None: This method returns nothing.
        """
        self.url = url
        self.plan = plan
        self.handlers = handlers
        self.closed = False

    def run_forever(self, **options):
        """Plays the plan and returns when the pretend connection closes.

        Args:
            **options (dict): The ping and TLS settings the socket asks for.

        Returns:
            None: This method returns nothing.
        """
        print(f'Connecting to {self.url}')
        if 'refuse_with' in self.plan:
            self.handlers['on_error'](self, HandshakeRefused(self.plan['refuse_with']))
            self.handlers['on_close'](self, None, None)
            return
        self.handlers['on_open'](self)
        for frame in self.plan['frames']:
            if self.closed:
                break
            self.handlers['on_message'](self, frame)
        self.handlers['on_close'](self, 1000, 'normal closure')

    def send(self, data, opcode=None):
        """Prints a message the socket sends to the broker.

        Args:
            data (str | bytes): The message.
            opcode (int | None): The frame type, when the socket names one.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(data, bytes):
            print(f'Sent binary frame: {data.hex()}')
        else:
            print(f'Sent: {data}')

    def close(self, **options):
        """Notes that the socket asked to close.

        Args:
            **options (dict): Any close status the socket passes.

        Returns:
            None: This method returns nothing.
        """
        self.closed = True


class ScriptedWebsocketModule:
    """A stand-in for the `websocket` package that hands out scripted connections in turn.

    Attributes:
        plans (list): What each connection does, in the order the socket connects.
        when_finished (callable | None): Called when the last connection is handed out, so the socket stops after it.
    """

    def __init__(self, plans):
        """Keeps the connection plans.

        Args:
            plans (list): What each connection does, in the order the socket connects.

        Returns:
            None: This method returns nothing.
        """
        self.plans = plans
        self.when_finished = None

    def WebSocketApp(self, url, **handlers):
        """Builds the next scripted connection, closing the socket after the last one.

        Args:
            url (str): The feed URL.
            **handlers (dict): The socket's `on_open`, `on_message`, `on_error` and `on_close` callbacks.

        Returns:
            ScriptedConnection: The connection.
        """
        if 'header' in handlers:
            print(f"Handshake header names: {list(handlers['header'])}")
        plan = self.plans.pop(0)
        if not self.plans:
            self.when_finished()
        return ScriptedConnection(url, plan, handlers)


class OrdersAndPositionsExample:
    """Runs the Fyers order update socket against one scripted connection.

    Attributes:
        socket (FyersOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the messages, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.fyers')
        api_module.FyersAPI = StandInFyersAPI
        sys.modules['stock_brokers.api.fyers'] = api_module
        subscribed = {
            's': 'ok',
            'code': 1605,
            'message': 'Successfully subscribed',
        }
        position = {
            's': 'ok',
            'positions': {
                'symbol': 'NSE:SBIN-EQ',
                'netQty': 10,
                'productType': 'INTRADAY',
            },
        }
        plans = [
            {
                'frames': [
                    json.dumps(subscribed),
                    'pong',
                    self.order_message(6, 0),
                    json.dumps(position),
                    self.order_message(2, 10),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('fyers.orders')
        self.socket = FyersOrderUpdatesSocket(FyersSession(logger), self.print_updates, logger)
        websocket_module.when_finished = self.socket.close

    def order_message(self, status, filled_quantity):
        """One of Fyers' order messages for an SBIN buy.

        Args:
            status (int): Fyers' numeric order status, 6 for pending and 2 for filled.
            filled_quantity (int): How much has filled.

        Returns:
            str: The message as JSON text.
        """
        message = {
            's': 'ok',
            'orders': {
                'id': '26092500012345',
                'symbol': 'NSE:SBIN-EQ',
                'status': status,
                'side': 1,
                'qty': 10,
                'filledQty': filled_quantity,
                'limitPrice': 820.5,
            },
        }
        return json.dumps(message)

    def print_updates(self, orders, positions, received_at):
        """Prints each order and position the socket handed on.

        Args:
            orders (list): The message's orders, exactly as Fyers sent them.
            positions (list): The message's positions, exactly as Fyers sent them.
            received_at (datetime.datetime): When the message arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        for order in orders:
            print(f"Order {order['id']} status {order['status']}: {order['filledQty']} of {order['qty']} {order['symbol']}")
        for position in positions:
            print(f"Position {position['symbol']}: net quantity {position['netQty']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    OrdersAndPositionsExample().run()
