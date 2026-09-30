"""Decodes INDstocks price feed updates, which are JSON inside JSON, and merges them into ticks.

`IndmoneyQuotesSocket` presents the token in the websocket handshake and subscribes its batch in `full` mode. Every update arrives as a JSON string whose content is itself JSON, one per line, so each line is decoded twice. An update names the instrument by its bare security id and carries only the fields that changed, so the socket maps the id back to the subscribed `SEGMENT:TOKEN` and merges each instrument's fields across updates. No tick is handed on until an instrument has a last price.

This program scripts one connection whose single frame holds two lines for NSE security 2885: the first carries the day's open, high, low, close and volume without a last price, and the second carries the last price, the best bid and offer and a millisecond timestamp. No real socket is opened: a stand-in `websocket` package plays the frame and prints the handshake headers and what the socket sends, and a stand-in `stock_brokers.api.indmoney` module lets the real `IndmoneySession` supply credentials without logging in.

Notice that only one tick comes out, that it holds the fields of both lines, that the millisecond timestamp becomes epoch seconds, and that the depth is the best bid and offer only, without quantities.

Run it from the project root:

    python examples/stock_brokers/websockets/indmoney/IndmoneyQuotesSocket/example_1_merging_double_encoded_updates.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.indmoney import (
    IndmoneyQuotesSocket,
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


class MergingDoubleEncodedUpdatesExample:
    """Runs an INDmoney quotes socket against one scripted frame of two lines.

    Attributes:
        socket (IndmoneyQuotesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the frame, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.indmoney')
        api_module.INDMoneyAPI = StandInINDMoneyAPI
        sys.modules['stock_brokers.api.indmoney'] = api_module
        day_fields = {
            'instrument': '2885',
            'data': {
                'open': 2930.0,
                'high': 2960.0,
                'low': 2925.0,
                'close': 2950.0,
                'volume': 1204500.0,
            },
        }
        price_fields = {
            'instrument': '2885',
            'timestamp': 1790311529000,
            'data': {
                'ltp': 2950.5,
                'ltt': 1790311528,
                'bid_price': 2950.0,
                'ask_price': 2950.5,
                'total_buy_qty': 54000,
                'total_sell_qty': 61000,
            },
        }
        frame = self.feed_line(day_fields) + self.feed_line(price_fields)
        plans = [
            {
                'frames': [
                    frame,
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('indmoney.quotes')
        tokens = [
            'NSE:2885',
        ]
        names = {
            'NSE:2885': 'NSE:RELIANCE',
        }
        self.socket = IndmoneyQuotesSocket('socket_0', tokens, names, IndmoneySession(logger), self.print_ticks, logger)
        websocket_module.when_finished = self.socket.close

    def feed_line(self, update):
        """One line as INDstocks sends it: a JSON string whose content is itself JSON, then a newline.

        Args:
            update (dict): The update.

        Returns:
            str: The line.
        """
        return json.dumps(json.dumps(update)) + '\n'

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket built.

        Args:
            ticks (list): The normalized ticks from one frame.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            print(f"Tick {tick['id']} ({tick['instrument_token']}) on {tick['exchange']}")
            print(f"  last_price={tick['last_price']} volume={tick['volume']} buy_quantity={tick['buy_quantity']} sell_quantity={tick['sell_quantity']}")
            print(f"  ohlc={tick['ohlc']}")
            print(f"  last_trade_time={tick['last_trade_time']} exchange_timestamp={tick['exchange_timestamp']}")
            print(f"  depth={tick['depth']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    MergingDoubleEncodedUpdatesExample().run()
