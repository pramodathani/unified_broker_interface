"""Shows Shoonya's order update socket logging in again, without checking, after Noren rejects its connect frame.

When the `ak` acknowledgement is not `OK`, `ShoonyaOrderUpdatesSocket` closes the connection, and its reconnect loop calls `ShoonyaSession.log_in_again_without_checking`, which logs in whether or not another process already replaced the token.

This program scripts two connections: the first is rejected, the second is accepted and delivers one completed order update. No real socket is opened: a stand-in `websocket` package plays the connections, and a stand-in `stock_brokers.api.shoonya` module counts each `ShoonyaAPI` construction as a login. The backoff is set to zero seconds.

Notice the error line for the rejection, the second login, and the new token in the second connect frame.

Run it from the project root:

    python examples/stock_brokers/websockets/shoonya/ShoonyaOrderUpdatesSocket/example_2_rejected_then_logged_in_again.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.shoonya import (
    ShoonyaOrderUpdatesSocket,
    ShoonyaSession,
)


class LoginRecord:
    """The Shoonya login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInShoonyaAPI:
    """A stand-in for `ShoonyaAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'shoonya-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'ucc_code': 'FA12345',
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
        plan = self.plans.pop(0)
        if not self.plans:
            self.when_finished()
        return ScriptedConnection(url, plan, handlers)


class RejectedThenLoggedInAgainExample:
    """Runs the Shoonya order update socket through a rejection and a good connection.

    Attributes:
        socket (ShoonyaOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the frames, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.shoonya')
        api_module.ShoonyaAPI = StandInShoonyaAPI
        sys.modules['stock_brokers.api.shoonya'] = api_module
        rejected = {
            't': 'ak',
            's': 'NOT_OK',
        }
        accepted = {
            't': 'ak',
            's': 'OK',
        }
        plans = [
            {
                'frames': [
                    json.dumps(rejected),
                ],
            },
            {
                'frames': [
                    json.dumps(accepted),
                    json.dumps(self.order_update('COMPLETE', '5')),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('shoonya.orders')
        self.socket = ShoonyaOrderUpdatesSocket(ShoonyaSession(logger), self.print_orders, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
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
            'uid': 'FA12345',
            'actid': 'FA12345',
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
        """Runs the socket's reconnect loop until the scripted connections run out.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    RejectedThenLoggedInAgainExample().run()
