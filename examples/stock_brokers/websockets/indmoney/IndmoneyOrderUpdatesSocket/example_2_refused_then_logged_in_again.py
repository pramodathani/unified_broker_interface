"""Shows INDmoney's order update socket logging in again, without checking, after a refused handshake.

When INDstocks refuses the order socket's handshake with HTTP 401, 403 or 513, `IndmoneyOrderUpdatesSocket` treats it as a dead session and its reconnect loop calls `IndmoneySession.log_in_again_without_checking`, which logs in whether or not another process already replaced the token.

This program scripts two connections: the first is refused with HTTP 401, and the second opens and delivers one completed order. No real socket is opened: a stand-in `websocket` package plays the connections and prints each handshake's headers, and a stand-in `stock_brokers.api.indmoney` module counts each `INDMoneyAPI` construction as one login. The backoff is set to zero seconds.

Notice the warning about the refused handshake, the second login, and the new token in the second handshake.

Run it from the project root:

    python examples/stock_brokers/websockets/indmoney/IndmoneyOrderUpdatesSocket/example_2_refused_then_logged_in_again.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.indmoney import (
    IndmoneyOrderUpdatesSocket,
    IndmoneySession,
)


class LoginRecord:
    """The INDmoney login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInINDMoneyAPI:
    """A stand-in for `INDMoneyAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'indmoney-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'client_id': 'ind-client-7',
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
        print(f"Handshake headers: {handlers.get('header')}")
        plan = self.plans.pop(0)
        if not self.plans:
            self.when_finished()
        return ScriptedConnection(url, plan, handlers)


class RefusedThenLoggedInAgainExample:
    """Runs the INDmoney order update socket through a refused handshake and a good connection.

    Attributes:
        socket (IndmoneyOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the messages, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.indmoney')
        api_module.INDMoneyAPI = StandInINDMoneyAPI
        sys.modules['stock_brokers.api.indmoney'] = api_module
        update = {
            'type': 'order',
            'data': self.order('COMPLETE', 5),
        }
        plans = [
            {
                'refuse_with': 401,
            },
            {
                'frames': [
                    json.dumps(update),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('indmoney.orders')
        self.socket = IndmoneyOrderUpdatesSocket(IndmoneySession(logger), self.print_orders, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
        websocket_module.when_finished = self.socket.close

    def order(self, status, filled_quantity):
        """An INDstocks order for a TCS sell.

        Args:
            status (str): The order status.
            filled_quantity (int): How much has filled.

        Returns:
            dict: The order.
        """
        return {
            'order_id': 'IND2609250001',
            'order_status': status,
            'trading_symbol': 'TCS',
            'exchange': 'NSE',
            'txn_type': 'SELL',
            'qty': 5,
            'filled_qty': filled_quantity,
            'price': 4120.0,
        }

    def print_orders(self, orders, received_at):
        """Prints each order the socket handed on.

        Args:
            orders (list): The orders of one message, exactly as INDstocks sent them.
            received_at (datetime.datetime): When the message arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        for order in orders:
            print(f"Order {order['order_id']} {order['order_status']}: {order['txn_type']} {order['filled_qty']} of {order['qty']} {order['trading_symbol']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connections run out.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    RefusedThenLoggedInAgainExample().run()
