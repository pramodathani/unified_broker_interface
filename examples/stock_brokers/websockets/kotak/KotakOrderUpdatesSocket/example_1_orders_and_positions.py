"""Connects Kotak's order update socket to the session's own host and prints the orders and positions it hands on.

`KotakOrderUpdatesSocket` connects to `wss://<host>/realtime`, where the host is the `base_url` Kotak assigned the session at login, and sends Kotak's connection frame: a raw string that looks like JSON but deliberately is not, with the access token and session id. Kotak acknowledges it with `{"ak": "ok", "type": "cn"}`, and from then on sends `order` and `position` messages whose `data` carries Kotak's abbreviated fields, handed on exactly as sent.

This program scripts one connection delivering the acknowledgement, an open order, a position and the order completed. No real socket is opened: a stand-in `websocket` package plays the messages and prints what the socket sends, and a stand-in `stock_brokers.api.kotak` module lets the real `KotakSession` supply the host, token and session id without logging in.

Notice the URL built from the session's host, the unquoted connection frame, and that orders and positions reach the callback as separate lists.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakOrderUpdatesSocket/example_1_orders_and_positions.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.kotak import (
    KotakOrderUpdatesSocket,
    KotakSession,
)


class LoginRecord:
    """The Kotak login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The access token in force now.
        session_id (str | None): The session id in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    session_id = None
    login_count = 0


class StandInKotakAPI:
    """A stand-in for `KotakAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered access token and session id.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'kotak-token-{LoginRecord.login_count}'
        LoginRecord.session_id = f'kotak-sid-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, session id and host, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
            'sid': LoginRecord.session_id,
            'base_url': 'https://e21.kotaksecurities.com/',
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
            print(f'Sent binary frame of type {data[2]}: {data.hex()}')
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


class FrameOpcodes:
    """The one websocket frame opcode the Kotak quotes socket names.

    Attributes:
        OPCODE_BINARY (int): The binary frame opcode.
    """

    OPCODE_BINARY = 2


class ScriptedWebsocketModule:
    """A stand-in for the `websocket` package that hands out scripted connections in turn.

    Attributes:
        plans (list): What each connection does, in the order the socket connects.
        when_finished (callable | None): Called when the last connection is handed out, so the socket stops after it.
        ABNF (FrameOpcodes): The frame opcodes, as `websocket.ABNF` holds them.
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
        self.ABNF = FrameOpcodes()

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


class OrdersAndPositionsExample:
    """Runs the Kotak order update socket against one scripted connection.

    Attributes:
        socket (KotakOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the messages, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.kotak')
        api_module.KotakAPI = StandInKotakAPI
        sys.modules['stock_brokers.api.kotak'] = api_module
        acknowledgement = {
            'ak': 'ok',
            'type': 'cn',
            'task': 'cn',
        }
        position = {
            'type': 'position',
            'data': {
                'trdSym': 'INFY-EQ',
                'exSeg': 'nse_cm',
                'flBuyQty': 10,
                'flSellQty': 0,
            },
        }
        plans = [
            {
                'frames': [
                    json.dumps(acknowledgement),
                    json.dumps(self.order('open', 0)),
                    json.dumps(position),
                    json.dumps(self.order('complete', 10)),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('kotak.orders')
        self.socket = KotakOrderUpdatesSocket(KotakSession(logger), self.print_updates, logger)
        websocket_module.when_finished = self.socket.close

    def print_updates(self, orders, positions, received_at):
        """Prints each order and position the socket handed on.

        Args:
            orders (list): The message's order `data` objects, exactly as Kotak sent them.
            positions (list): The message's position `data` objects, exactly as Kotak sent them.
            received_at (datetime.datetime): When the message arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        for order in orders:
            print(f"Order {order['nOrdNo']} {order['ordSt']}: {order['trnsTp']} {order['fldQty']} of {order['qty']} {order['trdSym']}")
        for position in positions:
            print(f"Position {position['trdSym']}: bought {position['flBuyQty']} sold {position['flSellQty']}")

    def order(self, status, filled_quantity):
        """One Kotak order update for an INFY buy, with Kotak's abbreviated fields.

        Args:
            status (str): Kotak's order status.
            filled_quantity (int): How much has filled.

        Returns:
            dict: The message.
        """
        return {
            'type': 'order',
            'data': {
                'nOrdNo': '260925000012345',
                'ordSt': status,
                'trdSym': 'INFY-EQ',
                'exSeg': 'nse_cm',
                'trnsTp': 'B',
                'qty': 10,
                'fldQty': filled_quantity,
                'prc': '1500.00',
            },
        }

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    OrdersAndPositionsExample().run()
