"""Shows a Dhan quotes socket logging in again after Dhan disconnects it for an expired token.

Dhan does not refuse a dead token at the handshake. It accepts the connection and then sends a disconnect packet whose reason code says why: 807 (token expired), 808 (authentication failed) or 809 (token invalid). `DhanQuotesSocket` treats those codes as a refused login, closes the connection, and its reconnect loop asks the shared `DhanSession` to log in again before connecting with the new token.

This program scripts two connections. The first opens and receives a disconnect packet with code 807, followed by a quote packet that is never delivered because the socket has already closed. The second opens with the new token and delivers a 50 byte quote packet for NSE_FNO security 35001. No real socket is opened: a stand-in `websocket` package plays the connections, and a stand-in `stock_brokers.api.dhan` module counts each `DhanAPI` construction as one login so the real `DhanSession` runs unchanged. The backoff is set to zero seconds.

Notice the warning about the disconnect packet, the second login, the new token in the second URL, and that a quote tick with no remembered previous close keeps the close from its own packet.

Run it from the project root:

    python examples/stock_brokers/websockets/dhan/DhanQuotesSocket/example_2_disconnected_for_an_expired_token.py
"""

import logging
import struct
import sys
import types

from stock_brokers.websockets.dhan import (
    DhanQuotesSocket,
    DhanSession,
)


class LoginRecord:
    """The Dhan login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInDhanAPI:
    """A stand-in for `DhanAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'dhan-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'client_id': '1100012345',
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


class DhanPackets:
    """Builds DhanHQ v2 market feed packets byte by byte, little endian, as `wss://api-feed.dhan.co` sends them."""

    def header(self, feed_code, length, segment_code, security_id):
        """The eight byte header every packet opens with.

        Args:
            feed_code (int): The response code, such as 8 for a full packet.
            length (int): The packet's length in bytes.
            segment_code (int): Dhan's numeric exchange segment, such as 1 for NSE_EQ.
            security_id (int): Dhan's security id.

        Returns:
            bytes: The header.
        """
        return struct.pack('<BhBi', feed_code, length, segment_code, security_id)

    def previous_close(self, segment_code, security_id, close):
        """A 16 byte previous close packet.

        Args:
            segment_code (int): Dhan's numeric exchange segment.
            security_id (int): Dhan's security id.
            close (float): The previous session's close.

        Returns:
            bytes: The packet.
        """
        return self.header(6, 16, segment_code, security_id) + struct.pack('<fi', close, 0)

    def open_interest(self, segment_code, security_id, open_interest):
        """A 12 byte open interest packet.

        Args:
            segment_code (int): Dhan's numeric exchange segment.
            security_id (int): Dhan's security id.
            open_interest (int): The open interest.

        Returns:
            bytes: The packet.
        """
        return self.header(5, 12, segment_code, security_id) + struct.pack('<i', open_interest)

    def trade_fields(self, last_price, wall_clock_epoch):
        """The trade fields quote and full packets share, from byte 8 to byte 34.

        Args:
            last_price (float): The last traded price.
            wall_clock_epoch (int): The last trade time as Dhan sends it, India wall clock seconds presented as an epoch.

        Returns:
            bytes: The fields.
        """
        return struct.pack('<fhifiii', last_price, 25, wall_clock_epoch, last_price - 1.5, 1204500, 54000, 61000)

    def quote(self, segment_code, security_id, last_price, wall_clock_epoch):
        """A 50 byte quote packet.

        Args:
            segment_code (int): Dhan's numeric exchange segment.
            security_id (int): Dhan's security id.
            last_price (float): The last traded price.
            wall_clock_epoch (int): The last trade time as Dhan sends it.

        Returns:
            bytes: The packet.
        """
        packet = self.header(4, 50, segment_code, security_id)
        packet = packet + self.trade_fields(last_price, wall_clock_epoch)
        return packet + struct.pack('<ffff', last_price - 20.0, last_price - 40.0, last_price + 10.0, last_price - 25.0)

    def full(self, segment_code, security_id, last_price, wall_clock_epoch):
        """A 162 byte full packet with open interest and five levels of depth.

        Args:
            segment_code (int): Dhan's numeric exchange segment.
            security_id (int): Dhan's security id.
            last_price (float): The last traded price.
            wall_clock_epoch (int): The last trade time as Dhan sends it.

        Returns:
            bytes: The packet.
        """
        packet = self.header(8, 162, segment_code, security_id)
        packet = packet + self.trade_fields(last_price, wall_clock_epoch)
        packet = packet + struct.pack('<iii', 0, 0, 0)
        packet = packet + struct.pack('<ffff', last_price - 20.0, last_price - 40.0, last_price + 10.0, last_price - 25.0)
        for level in range(5):
            packet = packet + struct.pack('<iihhff', 100 + level, 200 + level, 3 + level, 4 + level, last_price - 0.5 - level, last_price + 0.5 + level)
        return packet

    def ticker(self, segment_code, security_id, last_price, wall_clock_epoch):
        """A 16 byte ticker packet with the last price and the last trade time.

        Args:
            segment_code (int): Dhan's numeric exchange segment.
            security_id (int): Dhan's security id.
            last_price (float): The last traded price.
            wall_clock_epoch (int): The last trade time as Dhan sends it.

        Returns:
            bytes: The packet.
        """
        return self.header(2, 16, segment_code, security_id) + struct.pack('<fi', last_price, wall_clock_epoch)

    def disconnect(self, reason_code):
        """A 10 byte disconnect packet with Dhan's reason code.

        Args:
            reason_code (int): Why Dhan is disconnecting, such as 808 for a failed authentication.

        Returns:
            bytes: The packet.
        """
        return self.header(50, 10, 0, 0) + struct.pack('<h', reason_code)


class DisconnectedForAnExpiredTokenExample:
    """Runs a Dhan quotes socket through an expired token disconnect and a good connection.

    Attributes:
        socket (DhanQuotesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the messages, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.dhan')
        api_module.DhanAPI = StandInDhanAPI
        sys.modules['stock_brokers.api.dhan'] = api_module
        packets = DhanPackets()
        wall_clock_epoch = 1790311528 + 19800
        plans = [
            {
                'frames': [
                    packets.disconnect(807),
                    packets.quote(2, 35001, 25150.5, wall_clock_epoch),
                ],
            },
            {
                'frames': [
                    packets.quote(2, 35001, 25151.25, wall_clock_epoch),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('dhan.quotes')
        tokens = [
            'NSE_FNO:35001',
        ]
        names = {
            'NSE_FNO:35001': 'NFO:NIFTY26SEPFUT',
        }
        self.socket = DhanQuotesSocket('socket_0', tokens, names, DhanSession(logger), self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
        websocket_module.when_finished = self.socket.close

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket decoded.

        Args:
            ticks (list): The normalized ticks from one message.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            change = tick['change']
            if change is not None:
                change = round(change, 4)
            print(f"Tick {tick['id']} ({tick['instrument_token']}) on {tick['exchange']} in {tick['mode']} mode")
            print(f"  last_price={tick['last_price']} last_trade_time={tick['last_trade_time']} volume={tick['volume']}")
            print(f"  ohlc={tick['ohlc']} change={change}")
            print(f"  oi={tick['oi']}")
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
    DisconnectedForAnExpiredTokenExample().run()
