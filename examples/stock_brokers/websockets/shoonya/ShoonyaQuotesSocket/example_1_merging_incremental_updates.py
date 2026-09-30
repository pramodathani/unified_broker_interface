"""Authenticates a Shoonya quotes socket and merges Noren's incremental feed into full ticks.

A `ShoonyaQuotesSocket` sends Noren's connect frame when the connection opens and subscribes its batch only after the `ak` acknowledgement says `OK`. The feed is incremental: a touchline or depth acknowledgement (`tk`, `dk`) carries every field and names the instrument, and each update after it (`tf`, `df`) carries only what changed. The socket keeps the last state of each instrument and merges every update into it before building a tick, with every string converted to a number.

This program scripts one connection that answers the connect frame with `OK`, sends a depth acknowledgement for NSE token 2885 naming it RELIANCE-EQ, and then a depth update that changes only the last price and the best bid. No real socket is opened: a stand-in `websocket` package plays the frames and prints what the socket sends, and a stand-in `stock_brokers.api.shoonya` module lets the real `ShoonyaSession` log in without reaching Shoonya.

Notice that the new name is handed to `on_name` before the first tick is handed to `on_tick`, and that the second tick still has the open, high, low, volume and trade time from the acknowledgement although the update did not repeat them. The trade time `25-09-2026 10:15:28` becomes an epoch.

Run it from the project root:

    python examples/stock_brokers/websockets/shoonya/ShoonyaQuotesSocket/example_1_merging_incremental_updates.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.shoonya import (
    ShoonyaQuotesSocket,
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


class MergingIncrementalUpdatesExample:
    """Runs a Shoonya quotes socket against an acknowledgement and one update.

    Attributes:
        socket (ShoonyaQuotesSocket): The socket being shown.
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
        connect_acknowledgement = {
            't': 'ak',
            's': 'OK',
            'uid': 'FA12345',
        }
        depth_acknowledgement = {
            't': 'dk',
            'e': 'NSE',
            'tk': '2885',
            'ts': 'RELIANCE-EQ',
            'lp': '2950.50',
            'pc': '1.39',
            'c': '2910.00',
            'o': '2930.00',
            'h': '2960.00',
            'l': '2925.00',
            'v': '1204500',
            'ap': '2949.10',
            'ltt': '25-09-2026 10:15:28',
            'ft': '1790311529',
            'bp1': '2950.00',
            'bq1': '100',
            'bo1': '3',
            'sp1': '2950.50',
            'sq1': '120',
            'so1': '4',
        }
        depth_update = {
            't': 'df',
            'e': 'NSE',
            'tk': '2885',
            'lp': '2951.00',
            'pc': '1.41',
            'bp1': '2950.50',
            'bq1': '80',
            'ft': '1790311530',
        }
        plans = [
            {
                'frames': [
                    json.dumps(connect_acknowledgement),
                    json.dumps(depth_acknowledgement),
                    json.dumps(depth_update),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('shoonya.quotes')
        tokens = [
            'NSE|2885',
        ]
        names = {}
        session = ShoonyaSession(logger)
        self.socket = ShoonyaQuotesSocket('socket_0', tokens, names, session, self.print_name, self.print_tick, logger)
        websocket_module.when_finished = self.socket.close

    def print_name(self, token, name):
        """Prints an instrument an acknowledgement named.

        Args:
            token (str): The instrument's `EXCHANGE|TOKEN`.
            name (str): Its new name.

        Returns:
            None: This method returns nothing.
        """
        print(f'Name learned: {token} is {name}')

    def print_tick(self, tick):
        """Prints the main fields of one tick the socket built.

        Args:
            tick (dict): The normalized tick.

        Returns:
            None: This method returns nothing.
        """
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
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    MergingIncrementalUpdatesExample().run()
