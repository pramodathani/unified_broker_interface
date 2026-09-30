"""Shows a quotes socket logging in again after Kite refuses its token, then receiving an index quote.

When Kite refuses a dead access token it fails the websocket handshake with HTTP 403. `ZerodhaQuotesSocket` notes the refusal, its reconnect loop asks the shared `ZerodhaSession` to log in again, and the next connection uses the new token. This program scripts two connections: the first is refused with 403, and the second opens and delivers one 28 byte index quote for NIFTY 50 (token 256265, whose low byte 9 marks the indices segment).

No real socket is opened and no real login happens. The program registers a stand-in `websocket` package that hands out the two scripted connections and prints the URL of each, and a stand-in `stock_brokers.api.zerodha` module whose `ZerodhaAPI` counts its constructions as logins, so the real `ZerodhaSession` runs unchanged on top of it. The socket's backoff is set to zero seconds so the reconnect happens at once.

Notice that the second URL carries the new token, and that an index tick has no quantities and gets its percentage `change` from the last price and the close.

Run it from the project root:

    python examples/stock_brokers/websockets/zerodha/ZerodhaQuotesSocket/example_2_refused_token_logs_in_again.py
"""

import logging
import struct
import sys
import types

from stock_brokers.websockets.zerodha import (
    ZerodhaQuotesSocket,
    ZerodhaSession,
)


class KiteLoginRecord:
    """The login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInZerodhaAPI:
    """A stand-in for `ZerodhaAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        KiteLoginRecord.login_count = KiteLoginRecord.login_count + 1
        KiteLoginRecord.access_token = f'kite-token-{KiteLoginRecord.login_count}'
        self._settings = {
            'api_key': 'kite-api-key',
        }

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, or None before any login.
        """
        if KiteLoginRecord.access_token is None:
            return None
        return {
            'access_token': KiteLoginRecord.access_token,
        }


class HandshakeRefused(Exception):
    """A refused websocket handshake, carrying the HTTP status the way `websocket-client` does.

    Attributes:
        status_code (int): The HTTP status Kite answered with.
    """

    def __init__(self, status_code):
        """Keeps the status.

        Args:
            status_code (int): The HTTP status Kite answered with.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(f'Handshake status {status_code} Forbidden')
        self.status_code = status_code


class ScriptedConnection:
    """A stand-in for `websocket.WebSocketApp` that either refuses the handshake or plays frames.

    Attributes:
        url (str): The URL the socket asked for.
        plan (dict): Either a `refuse_with` status or a list of `frames`.
        handlers (dict): The socket's callbacks, by name.
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

    def run_forever(self, **options):
        """Plays the plan and returns when the pretend connection closes.

        Args:
            **options (dict): The ping settings the socket asks for.

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
            self.handlers['on_message'](self, frame)
        self.handlers['on_close'](self, 1000, 'normal closure')

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
    """A stand-in for the `websocket` package that hands out scripted connections in turn.

    Attributes:
        plans (list): What each connection does, in the order the socket connects.
        when_finished (callable | None): Called when the last connection has been handed out and has run.
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


class RefusedTokenLogsInAgainExample:
    """Runs a quotes socket through a refused handshake and a good connection.

    Attributes:
        socket (ZerodhaQuotesSocket): The socket being shown.
    """

    def __init__(self):
        """Registers the stand-ins and builds the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.zerodha')
        api_module.ZerodhaAPI = StandInZerodhaAPI
        sys.modules['stock_brokers.api.zerodha'] = api_module
        index_values = [
            256265,
            2515065,
            2521000,
            2498000,
            2500000,
            2490000,
            150000,
        ]
        index_packet = b''
        for value in index_values:
            index_packet = index_packet + struct.pack('>I', value)
        frame = struct.pack('>H', 1) + struct.pack('>H', len(index_packet)) + index_packet
        plans = [
            {
                'refuse_with': 403,
            },
            {
                'frames': [
                    frame,
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('zerodha.quotes')
        session = ZerodhaSession(logger)
        tokens = [
            256265,
        ]
        names = {
            '256265': 'NSE:NIFTY 50',
        }
        self.socket = ZerodhaQuotesSocket('socket_0', tokens, names, session, self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
        websocket_module.when_finished = self.socket.close

    def print_ticks(self, ticks):
        """Prints each index tick the socket decoded.

        Args:
            ticks (list): The normalized ticks from one frame.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            print(f"Tick {tick['id']} on {tick['exchange']} in {tick['mode']} mode")
            print(f"  last_price={tick['last_price']} volume={tick['volume']} change={round(tick['change'], 4)}")
            print(f"  ohlc={tick['ohlc']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connections run out.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {KiteLoginRecord.login_count}')


if __name__ == '__main__':
    RefusedTokenLogsInAgainExample().run()
