"""Shows a Kotak quotes socket logging in again after a refused session, then surviving a truncated data frame.

When Kotak answers the connection request with a status other than `K`, `KotakQuotesSocket` closes the connection as a refused login, and its reconnect loop asks the shared `KotakSession` to log in again unless another socket or process already replaced the session. A data frame that ends before a field it declared raises `KotakTruncatedFrameError` inside the socket, which logs a warning and still hands on the ticks of the packets it had read.

This program's first connection is refused with status `N`. The second is accepted without acknowledgements being asked for (an interval of 0), and its data frame holds a whole scrip snapshot followed by an update packet cut short. No real socket is opened: a stand-in `websocket` package plays the frames, and a stand-in `stock_brokers.api.kotak` module counts each `KotakAPI` construction as one login. The backoff is set to zero seconds.

Notice the new token and session id in the second connection request, the warning about the truncated frame, and that the snapshot's tick still arrives in quote mode because no depth topic was sent.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakQuotesSocket/example_2_refused_session_and_truncated_frame.py
"""

import logging
import sys
import types

from stock_brokers.websockets.kotak import (
    KotakQuotesSocket,
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


class HsmFeedFrames:
    """Builds the binary frames Kotak's HSM feed sends, big endian."""

    def framed(self, frame_type, body):
        """A frame: its length, its type and its body.

        Args:
            frame_type (int): The frame type.
            body (bytes): Everything after the type.

        Returns:
            bytes: The frame.
        """
        content = bytes([frame_type]) + body
        return len(content).to_bytes(2, 'big') + content

    def status_field(self, status):
        """A status field: id 1, a two-byte length and the status.

        Args:
            status (str): The status letter.

        Returns:
            bytes: The field.
        """
        return bytes([1]) + len(status).to_bytes(2, 'big') + status.encode('latin-1')

    def connection_response(self, status, acknowledge_every):
        """A connection response with a status and the acknowledgement interval.

        Args:
            status (str): `K` for accepted.
            acknowledge_every (int): After how many data frames Kotak wants an acknowledgement.

        Returns:
            bytes: The frame.
        """
        acknowledgement = bytes([2]) + (4).to_bytes(2, 'big') + acknowledge_every.to_bytes(4, 'big')
        return self.framed(1, bytes([2]) + self.status_field(status) + acknowledgement)

    def subscription_response(self):
        """An accepted subscription response.

        Returns:
            bytes: The frame.
        """
        return self.framed(4, bytes([1]) + self.status_field('K'))

    def numbers(self, values):
        """Numeric fields, four signed bytes each, with None as Kotak's unchanged marker.

        Args:
            values (list): The values.

        Returns:
            bytes: The packed values.
        """
        packed = bytes([len(values)])
        for value in values:
            if value is None:
                value = -2147483648
            packed = packed + value.to_bytes(4, 'big', signed=True)
        return packed

    def snapshot(self, topic_id, topic_name, values, trading_symbol):
        """A snapshot packet carrying the trading symbol as string field 54.

        Args:
            topic_id (int): The topic id updates refer to.
            topic_name (str): The topic name, such as `sf|nse_cm|2885`.
            values (list): The numeric fields in field order.
            trading_symbol (str): The trading symbol.

        Returns:
            bytes: The packet, after its two-byte length.
        """
        name = topic_name.encode('latin-1')
        symbol = trading_symbol.encode('latin-1')
        body = bytes([83]) + topic_id.to_bytes(4, 'big', signed=True) + bytes([len(name)]) + name + self.numbers(values)
        body = body + bytes([1, 54, len(symbol)]) + symbol
        return len(body).to_bytes(2, 'big') + body

    def update(self, topic_id, values):
        """An update packet.

        Args:
            topic_id (int): The topic id.
            values (list): The numeric fields in field order.

        Returns:
            bytes: The packet, after its two-byte length.
        """
        body = bytes([85]) + topic_id.to_bytes(4, 'big', signed=True) + self.numbers(values)
        return len(body).to_bytes(2, 'big') + body

    def data(self, message_number, packets):
        """A data frame, with a message number when acknowledgements were asked for.

        Args:
            message_number (int | None): The message number an acknowledgement refers to, or None when acknowledgements were not asked for.
            packets (list): The packets.

        Returns:
            bytes: The frame.
        """
        body = b''
        if message_number is not None:
            body = message_number.to_bytes(4, 'big', signed=True)
        body = body + len(packets).to_bytes(2, 'big')
        for packet in packets:
            body = body + packet
        return self.framed(6, body)

    def scrip_values(self, last_price, volume):
        """The 25 scrip fields of an NSE equity, with prices in paise, a multiplier of 1 and a precision of 2.

        Args:
            last_price (int): The last price in paise.
            volume (int): The day's volume.

        Returns:
            list: The fields in field order.
        """
        values = []
        for _ in range(25):
            values.append(None)
        values[2] = 1790311529
        values[3] = 1790311528
        values[4] = volume
        values[5] = last_price
        values[6] = 25
        values[7] = 54000
        values[8] = 61000
        values[13] = last_price - 150
        values[14] = 292500
        values[15] = 296000
        values[20] = 293000
        values[21] = 291000
        values[22] = 0
        values[23] = 1
        values[24] = 2
        return values

    def depth_values(self):
        """The 34 depth fields of five levels a side, with prices in paise.

        Returns:
            list: The fields in field order.
        """
        values = []
        for _ in range(34):
            values.append(None)
        for level in range(5):
            values[2 + level] = 295000 - level * 5
            values[7 + level] = 295100 + level * 5
            values[12 + level] = 100 + level
            values[17 + level] = 200 + level
            values[22 + level] = 3 + level
            values[27 + level] = 4 + level
        values[32] = 1
        values[33] = 2
        return values


class RefusedSessionAndTruncatedFrameExample:
    """Runs a Kotak quotes socket through a refused session and a truncated frame.

    Attributes:
        socket (KotakQuotesSocket): The socket being shown.
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
        frames = HsmFeedFrames()
        update = frames.update(3, [
            None,
            None,
            None,
            None,
            1205000,
            295100,
        ])
        truncated = frames.data(None, [
            frames.snapshot(3, 'sf|nse_cm|2885', frames.scrip_values(295050, 1204500), 'RELIANCE-EQ'),
            update[:9],
        ])
        plans = [
            {
                'frames': [
                    frames.connection_response('N', 0),
                ],
            },
            {
                'frames': [
                    frames.connection_response('K', 0),
                    truncated,
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('kotak.quotes')
        instrument_tokens = [
            'nse_cm|2885',
        ]
        names = {
            'nse_cm|2885': 'RELIANCE-EQ',
        }
        session = KotakSession(logger)
        self.socket = KotakQuotesSocket('socket_0', instrument_tokens, names, session, self.print_name, self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
        websocket_module.when_finished = self.socket.close

    def print_name(self, instrument_token, trading_symbol):
        """Prints an instrument a snapshot named.

        Args:
            instrument_token (str): The instrument's `EXCHANGE|TOKEN`.
            trading_symbol (str): Its trading symbol.

        Returns:
            None: This method returns nothing.
        """
        print(f'Name learned: {instrument_token} is {trading_symbol}')

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket built.

        Args:
            ticks (list): The normalized ticks from one data frame.

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
            if tick['depth']['buy']:
                print(f"  best bid={tick['depth']['buy'][0]} best offer={tick['depth']['sell'][0]} levels={len(tick['depth']['buy'])}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connections run out.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    RefusedSessionAndTruncatedFrameExample().run()
