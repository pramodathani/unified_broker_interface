"""Authenticates Flattrade's order update socket, subscribes to the account and prints the order updates it hands on.

`FlattradeOrderUpdatesSocket` sends Noren's connect frame when the connection opens, and once the `ak` acknowledgement says `OK` it subscribes to the whole account with `{"t": "o", "actid": ...}`. Every change to an order then arrives as an `om` message, and the socket hands each frame's `om` updates that carry an order number on, exactly as Noren sent them. In production Flattrade permits one websocket per session, so this socket is not run there; the program shows what it does when it is.

This program scripts one connection that sends the acknowledgement and then one frame holding a list of two `om` updates and a message of another type. No real socket is opened: a stand-in `websocket` package plays the frames and prints what the socket sends, and a stand-in `stock_brokers.api.flattrade` module lets the real `FlattradeSession` log in and confirm its session without reaching Flattrade.

Notice the connect frame and the account subscription in the output, and that both updates of the list reach the callback in one call.

Run it from the project root:

    python examples/stock_brokers/websockets/flattrade/FlattradeOrderUpdatesSocket/example_1_subscribing_to_the_account.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.flattrade import (
    FlattradeOrderUpdatesSocket,
    FlattradeSession,
)


class LoginRecord:
    """The Flattrade login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
        refused_logins (set): The login numbers whose session UserDetails refuses.
    """

    access_token = None
    login_count = 0
    refused_logins = set()


class StandInFlattradeAPI:
    """A stand-in for `FlattradeAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'flattrade-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'username': 'FT012345',
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

    def post(self, url, timeout):
        """Answers the UserDetails call the session confirms every login with.

        Args:
            url (str): The endpoint the session calls.
            timeout (int): The request timeout in seconds.

        Returns:
            dict: What the real class returns, with Noren's answer under `data`.
        """
        status = 'Ok'
        if LoginRecord.login_count in LoginRecord.refused_logins:
            status = 'Not_Ok'
        print(f'UserDetails called for {LoginRecord.access_token}: {status}')
        return {
            'data': {
                'stat': status,
                'uname': 'EXAMPLE USER',
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
        plan = self.plans.pop(0)
        if not self.plans:
            self.when_finished()
        return ScriptedConnection(url, plan, handlers)


class SubscribingToTheAccountExample:
    """Runs the Flattrade order update socket against one scripted connection.

    Attributes:
        socket (FlattradeOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the frames, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.flattrade')
        api_module.FlattradeAPI = StandInFlattradeAPI
        sys.modules['stock_brokers.api.flattrade'] = api_module
        acknowledgement = {
            't': 'ak',
            's': 'OK',
        }
        batch = [
            self.order_update('OPEN', '0'),
            self.order_update('COMPLETE', '5'),
            {
                't': 'dk',
                'e': 'NSE',
            },
        ]
        plans = [
            {
                'frames': [
                    json.dumps(acknowledgement),
                    json.dumps(batch),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('flattrade.orders')
        self.socket = FlattradeOrderUpdatesSocket(FlattradeSession(logger), self.print_orders, logger)
        websocket_module.when_finished = self.socket.close

    def order_update(self, status, filled_quantity):
        """One Noren `om` order update for a TCS sell, every value a string.

        Args:
            status (str): Noren's order status.
            filled_quantity (str): How much has filled.

        Returns:
            dict: The update.
        """
        return {
            't': 'om',
            'norenordno': '26092500012345',
            'uid': 'FT012345',
            'actid': 'FT012345',
            'exch': 'NSE',
            'tsym': 'TCS-EQ',
            'trantype': 'S',
            'qty': '5',
            'fillshares': filled_quantity,
            'prc': '4120.00',
            'prctyp': 'LMT',
            'status': status,
        }

    def print_orders(self, orders, received_at):
        """Prints each order update the socket handed on.

        Args:
            orders (list): The `om` updates of one frame, exactly as Noren sent them.
            received_at (datetime.datetime): When the frame arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        print(f'Callback received {len(orders)} update(s)')
        for order in orders:
            print(f"  Order {order['norenordno']} {order['status']}: {order['trantype']} {order['fillshares']} of {order['qty']} {order['tsym']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    SubscribingToTheAccountExample().run()
