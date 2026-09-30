"""Shows a Flattrade quotes socket logging in again when Noren refuses its connect frame.

Noren accepts every websocket handshake and refuses a dead session in its `ak` acknowledgement instead, with a status other than `OK`. `FlattradeQuotesSocket` then closes the connection and its reconnect loop asks the shared `FlattradeSession` to log in again, which the session confirms against UserDetails before the socket connects with the new token.

This program scripts two connections. The first answers the connect frame with `NOT_OK`. The second accepts it and sends a touchline acknowledgement for MCX token 565899 whose trade time is a bare India clock time, `10:15:28`, and a touchline acknowledgement for a token with no price yet. No real socket is opened: a stand-in `websocket` package plays the connections, and a stand-in `stock_brokers.api.flattrade` module counts each `FlattradeAPI` construction as a login. The backoff is set to zero seconds.

Notice the second login and its UserDetails check, the new token in the second connect frame, and that the bare clock time is dated by the frame's feed time. The instrument without a price is named but produces no tick.

Run it from the project root:

    python examples/stock_brokers/websockets/flattrade/FlattradeQuotesSocket/example_2_refused_acknowledgement.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.flattrade import (
    FlattradeQuotesSocket,
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


class RefusedAcknowledgementExample:
    """Runs a Flattrade quotes socket through a refused connect frame and a good connection.

    Attributes:
        socket (FlattradeQuotesSocket): The socket being shown.
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
        refused = {
            't': 'ak',
            's': 'NOT_OK',
            'emsg': 'Session Expired :  Invalid Session Key',
        }
        accepted = {
            't': 'ak',
            's': 'Ok',
        }
        crude_touchline = {
            't': 'tk',
            'e': 'MCX',
            'tk': '565899',
            'ts': 'CRUDEOIL19OCT26',
            'lp': '6120.00',
            'c': '6100.00',
            'v': '8450',
            'oi': '12500',
            'ltt': '10:15:28',
            'ft': '1790311529',
        }
        unpriced_touchline = {
            't': 'tk',
            'e': 'MCX',
            'tk': '565900',
            'ts': 'CRUDEOIL19NOV26',
            'lp': 'NA',
        }
        plans = [
            {
                'frames': [
                    json.dumps(refused),
                ],
            },
            {
                'frames': [
                    json.dumps(accepted),
                    json.dumps(crude_touchline),
                    json.dumps(unpriced_touchline),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('flattrade.quotes')
        tokens = [
            'MCX|565899',
            'MCX|565900',
        ]
        names = {}
        session = FlattradeSession(logger)
        self.socket = FlattradeQuotesSocket('socket_0', tokens, names, session, self.print_names, self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
        websocket_module.when_finished = self.socket.close

    def print_names(self, named):
        """Prints the instruments a frame newly named.

        Args:
            named (dict): Tokens to their new names.

        Returns:
            None: This method returns nothing.
        """
        print(f'Names learned: {named}')

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket built.

        Args:
            ticks (list): The normalized ticks from one frame.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            change = tick['change']
            if change is not None:
                change = round(change, 4)
            print(f"Tick {tick['id']} ({tick['instrument_token']}) in {tick['mode']} mode")
            print(f"  last_price={tick['last_price']} volume={tick['volume']} change={change}")
            print(f"  ohlc={tick['ohlc']}")
            print(f"  last_trade_time={tick['last_trade_time']} exchange_timestamp={tick['exchange_timestamp']}")
            if tick['depth']['buy']:
                print(f"  best bid={tick['depth']['buy'][0]} best offer={tick['depth']['sell'][0]}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connections run out.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    RefusedAcknowledgementExample().run()
