"""Shows a Kotak SFeed quotes socket logging in again after Kotak refuses its session, then reconnecting and streaming.

Kotak checks the session id in the authentication message only after answering it: the socket subscribes on the 1119 answer as usual, and then message code 1120 says the session was refused. `KotakQuotesSocket` logs the refusal by its message code alone, because Kotak's text repeats the session id, marks the connection as a rejected login and closes it. Its reconnect loop then asks the shared `KotakSession` to log in again, which it does only when the refused session id is still the one in force, and reconnects with the new login. Every connect reads the feed address afresh, so a `feed_url` the new login stored is used at once.

This program's first connection is answered with 1119 and then refused with 1120; the acknowledgement scripted after the refusal is never delivered, because the socket has closed. The stand-in login that follows issues a new session id and stores its own feed address, `wss://sfeed-e21.kotaksecurities.com/apifeed`, where the first login stored none. The second connection is answered with 1119 and 1109 and carries one data frame for RELIANCE (`nse_cm|2885`). No real socket is opened: a stand-in `websocket` package plays the frames and prints each text message the socket sends, and a stand-in `stock_brokers.api.kotak` module counts each `KotakAPI` construction as one login. The backoff is set to zero seconds, and the clock is fixed at 09:15 IST on 2026-10-28, because the authentication message carries the time of the request.

Notice that the refused session id `kotak-sid-1` appears only in the first authentication message and never in the log, that the second connection goes to the new feed address with `kotak-sid-2`, and that two logins were made in all.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakQuotesSocket/example_2_refused_session_and_logging_in_again.py
"""

import datetime
import json
import logging
import struct
import sys
import types
import zoneinfo
from unittest import mock

from stock_brokers.websockets.kotak import (
    KotakQuotesSocket,
    KotakSession,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
PACKET_HEADER = struct.Struct('<HHbBBBB')
MARKET_PICTURE = struct.Struct('<IqqqqqIIIIIqIIIIhiIdiIIIIIBI')
DEPTH_ROW = struct.Struct('<qii')
MARKET_PICTURE_CODE = 7208
NSE_CM = 1


class LoginRecord:
    """The Kotak login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The access token in force now.
        session_id (str | None): The session id in force now.
        feed_url (str | None): The market feed address the login stored, None when it stored none.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    session_id = None
    feed_url = None
    login_count = 0


class StandInKotakAPI:
    """A stand-in for `KotakAPI` whose construction is a pretend login.

    Attributes:
        _settings (dict): The account's settings, as the real class reads them from MongoDB.
    """

    def __init__(self):
        """Logs in, which here only issues the next numbered access token and session id.

        Returns:
            None: This method returns nothing.
        """
        self._settings = {
            'ucc_code': 'ABCD1',
        }
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'kotak-token-{LoginRecord.login_count}'
        LoginRecord.session_id = f'kotak-sid-{LoginRecord.login_count}'
        if LoginRecord.login_count > 1:
            LoginRecord.feed_url = 'wss://sfeed-e21.kotaksecurities.com/apifeed'
        print(f'Stand-in login number {LoginRecord.login_count}')

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, session id, host and feed address, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
            'sid': LoginRecord.session_id,
            'base_url': 'https://e21.kotaksecurities.com/',
            'feed_url': LoginRecord.feed_url,
        }


class ScriptedConnection:
    """A stand-in for `websocket.WebSocketApp` that plays frames to the socket's handlers.

    Attributes:
        url (str): The URL the socket asked for.
        frames (list): The text and binary frames to deliver, in order.
        handlers (dict): The socket's callbacks, by name.
        closed (bool): Whether the socket asked to close, after which no more frames are delivered.
    """

    def __init__(self, url, frames, handlers):
        """Keeps what the socket passed in.

        Args:
            url (str): The URL the socket asked for.
            frames (list): The text and binary frames to deliver, in order.
            handlers (dict): The socket's callbacks, by name.

        Returns:
            None: This method returns nothing.
        """
        self.url = url
        self.frames = frames
        self.handlers = handlers
        self.closed = False

    def run_forever(self, **options):
        """Plays the frames and returns when the pretend connection closes.

        Args:
            **options (dict): The ping settings the socket asks for.

        Returns:
            None: This method returns nothing.
        """
        print(f'Connecting to {self.url}')
        self.handlers['on_open'](self)
        for frame in self.frames:
            if self.closed:
                break
            if isinstance(frame, bytes):
                print(f'Kotak sends a binary frame of {len(frame)} bytes')
            else:
                print(f'Kotak sends message code {json.loads(frame)["message_code"]}')
            self.handlers['on_message'](self, frame)
        self.handlers['on_close'](self, 1000, 'normal closure')

    def send(self, data, opcode=None):
        """Prints a message the socket sends to the broker.

        Args:
            data (str): The message.
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
        plans (list): The frames of each connection, in the order the socket connects.
        when_finished (callable | None): Called when the last connection is handed out, so the socket stops after it.
    """

    def __init__(self, plans):
        """Keeps the connection plans.

        Args:
            plans (list): The frames of each connection, in the order the socket connects.

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
        frames = self.plans.pop(0)
        if not self.plans:
            self.when_finished()
        return ScriptedConnection(url, frames, handlers)


class SfeedFrames:
    """Builds the JSON control messages and little-endian binary packets of Kotak's SFeed feed."""

    def authentication_answer(self, message_code):
        """An answer to the authentication message, carrying the exchanges and their price dividers.

        Args:
            message_code (int): 1119 or 1117.

        Returns:
            str: The message.
        """
        return json.dumps({
            'message_code': message_code,
            'format': 'native_batch',
            'exchanges': {
                'nse_cm': {
                    'value': NSE_CM,
                    'divider': 100,
                },
            },
        })

    def refusal(self, session_id):
        """Kotak's refusal of the session, whose text repeats the session id.

        Args:
            session_id (str): The refused session id.

        Returns:
            str: The message.
        """
        return json.dumps({
            'message_code': 1120,
            'message': f'Auth failed {session_id} NEOTRADEAPI',
        })

    def acknowledgement(self, trading_symbols):
        """The subscription acknowledgement, naming each instrument.

        Args:
            trading_symbols (dict): `EXCHANGE|TOKEN` to trading symbol.

        Returns:
            str: The message.
        """
        return json.dumps({
            'message_code': 1109,
            'error_code': 0,
            'description': 'SUBSCRIBED',
            'trading_symbols': trading_symbols,
        })

    def market_picture(self, token, last_price, close, volume):
        """A level-8 NSE market picture with five depth rows a side around the last price.

        Args:
            token (int): The instrument's token.
            last_price (int): The last price in paise.
            close (int): The previous close in paise.
            volume (int): The day's volume.

        Returns:
            bytes: The packet.
        """
        body = MARKET_PICTURE.pack(
            token,
            54000,
            61000,
            volume,
            1793159100,
            1793159101,
            close,
            close,
            last_price + 500,
            close - 500,
            last_price,
            25,
            last_price,
            0,
            5,
            5,
            0,
            0,
            0,
            0.0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        for level in range(5):
            body = body + DEPTH_ROW.pack(100 + level, last_price - 5 - level * 5, 3 + level)
        for level in range(5):
            body = body + DEPTH_ROW.pack(200 + level, last_price + 5 + level * 5, 4 + level)
        length = PACKET_HEADER.size + len(body)
        return PACKET_HEADER.pack(length, MARKET_PICTURE_CODE, NSE_CM, 8, 0, 1, 0) + body


class RefusedSessionAndLoggingInAgainExample:
    """Runs a Kotak quotes socket through a refused session and a reconnect with a new login.

    Attributes:
        names (dict): `EXCHANGE|TOKEN` to trading symbol, shared with the socket.
        socket (KotakQuotesSocket): The socket being shown.
        requested_at (float): The fixed clock reading, in Unix seconds.
    """

    def __init__(self):
        """Builds the frames, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.kotak')
        api_module.KotakAPI = StandInKotakAPI
        sys.modules['stock_brokers.api.kotak'] = api_module
        requested = datetime.datetime(2026, 10, 28, 9, 15, tzinfo=INDIA)
        self.requested_at = requested.timestamp()
        frames = SfeedFrames()
        trading_symbols = {
            'nse_cm|2885': 'RELIANCE-EQ',
        }
        plans = [
            [
                frames.authentication_answer(1119),
                frames.refusal('kotak-sid-1'),
                frames.acknowledgement(trading_symbols),
            ],
            [
                frames.authentication_answer(1119),
                frames.acknowledgement(trading_symbols),
                frames.market_picture(2885, 119845, 119620, 1204500),
            ],
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('kotak.quotes')
        instrument_tokens = [
            'nse_cm|2885',
        ]
        self.names = {
            'nse_cm|2885': 'RELIANCE-EQ',
        }
        session = KotakSession(logger)
        self.socket = KotakQuotesSocket('socket_0', instrument_tokens, self.names, session, self.print_name, self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
        websocket_module.when_finished = self.socket.close

    def print_name(self, instrument_token, trading_symbol):
        """Prints an instrument the acknowledgement named.

        Args:
            instrument_token (str): The instrument's `EXCHANGE|TOKEN`.
            trading_symbol (str): Its trading symbol.

        Returns:
            None: This method returns nothing.
        """
        print(f'Name learned: {instrument_token} is {trading_symbol}')

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket handed on.

        Args:
            ticks (list): The normalized ticks from one data frame.

        Returns:
            None: This method returns nothing.
        """
        print(f'Ticks handed on: {len(ticks)}')
        for tick in ticks:
            change = round(tick['change'], 4)
            print(f"  {tick['id']} ({tick['instrument_token']}) in {tick['mode']} mode: last_price={tick['last_price']} volume={tick['volume']} change={change}")
            print(f"    best bid={tick['depth']['buy'][0]} best offer={tick['depth']['sell'][0]} levels={len(tick['depth']['buy'])}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connections run out.

        Returns:
            None: This method returns nothing.
        """
        with mock.patch('time.time', return_value=self.requested_at):
            self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    RefusedSessionAndLoggingInAgainExample().run()
