"""Shows a Fyers quotes socket logging in once for an expired token and giving up when the feed still refuses it.

`FyersQuotesSocket` has a reconnect loop of its own, `run_forever`, because a Cloudflare ban or rate limit on the symbol lookup must pause the socket for minutes rather than log in again. Otherwise it follows the shared loop: a refusal logs in again once, and a refusal straight after that login makes the socket give up so its script can exit and let systemd restart it. The access token is a JWT, and a token whose `exp` has passed is treated as refused without sending anything, because Fyers' edge bans addresses that keep sending refused requests.

This program's first login issues an already expired token, so the first connect sends nothing and logs in again. The second connect resolves the symbol and opens, but the feed refuses the hsm key with an `N` in its authentication response, so the socket gives up. No real socket or HTTP request is made: stand-in `websocket` and `requests` packages play the connection and the lookup, and a stand-in `stock_brokers.api.fyers` module issues the tokens and serves the profile. The backoff is set to zero seconds; the ban and rate limit pauses are not shown because they wait for minutes.

Notice that the expired token never reaches the network, that each login is confirmed against the profile, and that `gave_up` ends True.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersQuotesSocket/example_2_expired_token_then_refused_feed.py
"""

import base64
import json
import logging
import struct
import sys
import types

from stock_brokers.websockets.fyers import (
    FyersQuotesSocket,
    FyersSession,
)


class LoginRecord:
    """The Fyers login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
        expired_logins (set): The login numbers whose token has already expired.
        refused_profiles (set): The login numbers whose session the profile endpoint refuses.
    """

    access_token = None
    login_count = 0
    expired_logins = set()
    refused_profiles = set()


class StandInFyersAPI:
    """A stand-in for `FyersAPI` whose construction is a pretend login that issues a JWT access token."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        expiry = 4102444800
        if LoginRecord.login_count in LoginRecord.expired_logins:
            expiry = 1
        claims = {
            'exp': expiry,
            'hsm_key': f'hsm-key-{LoginRecord.login_count}',
        }
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        LoginRecord.access_token = f'header.{payload}.signature'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'app_id': 'XY1234-100',
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

    def get(self, url, timeout):
        """Answers the profile call the session confirms every login with.

        Args:
            url (str): The endpoint the session calls.
            timeout (int): The request timeout in seconds.

        Returns:
            dict: What the real class returns, with Fyers' answer under `data`.
        """
        if LoginRecord.login_count in LoginRecord.refused_profiles:
            print(f'Profile refused for login {LoginRecord.login_count}')
            return {
                'data': {
                    's': 'error',
                    'code': -16,
                    'message': 'Could not authenticate the user',
                },
            }
        print(f'Profile served for login {LoginRecord.login_count}')
        return {
            'data': {
                's': 'ok',
                'data': {
                    'fy_id': 'XY01234',
                },
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
        if isinstance(data, bytes):
            print(f'Sent binary frame: {data.hex()}')
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
        if 'header' in handlers:
            print(f"Handshake header names: {list(handlers['header'])}")
        plan = self.plans.pop(0)
        if not self.plans:
            self.when_finished()
        return ScriptedConnection(url, plan, handlers)


class SymbolLookupResponse:
    """A stand-in for the `requests` response of Fyers' symbol-token endpoint.

    Attributes:
        status_code (int): The HTTP status.
        body (dict): The JSON body.
        text (str): The body as text.
    """

    def __init__(self, status_code, body):
        """Keeps the answer.

        Args:
            status_code (int): The HTTP status.
            body (dict): The JSON body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.body = body
        self.text = json.dumps(body)

    def json(self):
        """The JSON body.

        Returns:
            dict: The body.
        """
        return self.body


class StandInRequests:
    """A stand-in for the `requests` package that answers the symbol lookup from a fixed table.

    Attributes:
        fytokens (dict): Each Fyers symbol to its fytoken.
    """

    def __init__(self, fytokens):
        """Keeps the table.

        Args:
            fytokens (dict): Each Fyers symbol to its fytoken.

        Returns:
            None: This method returns nothing.
        """
        self.fytokens = fytokens

    def post(self, url, headers, json, timeout):
        """Answers one symbol lookup.

        Args:
            url (str): The endpoint.
            headers (dict): The request headers.
            json (dict): The request body with its `symbols`.
            timeout (int): The request timeout in seconds.

        Returns:
            SymbolLookupResponse: The answer.
        """
        print(f"Symbol lookup for {json['symbols']}")
        valid = {}
        invalid = []
        for symbol in json['symbols']:
            if symbol in self.fytokens:
                valid[symbol] = self.fytokens[symbol]
            else:
                invalid.append(symbol)
        body = {
            's': 'ok',
            'validSymbol': valid,
            'invalidSymbol': invalid,
        }
        return SymbolLookupResponse(200, body)


class HsmResponses:
    """Builds the binary frames Fyers' HSM feed sends, byte by byte."""

    def auth_response(self, accepted, ack_count):
        """An authentication response.

        Args:
            accepted (bool): Whether the feed accepted the hsm key.
            ack_count (int): How many data messages to acknowledge at a time.

        Returns:
            bytes: The frame.
        """
        status = b'K'
        if not accepted:
            status = b'N'
        return struct.pack('!HBBBH', 0, 1, 2, 1, 1) + status + bytes([2]) + struct.pack('!H', 4) + struct.pack('>I', ack_count)

    def values(self, values):
        """Positional field values, with None as Fyers' no-value marker.

        Args:
            values (list): The values.

        Returns:
            bytes: The packed values.
        """
        packed = b''
        for value in values:
            if value is None:
                value = -2147483648
            packed = packed + struct.pack('>i', value)
        return packed

    def snapshot(self, topic_id, topic_name, values):
        """A snapshot packet naming a topic and carrying every field, then a precision of 2 and three strings.

        Args:
            topic_id (int): The topic id later updates refer to.
            topic_name (str): The topic name.
            values (list): The positional values.

        Returns:
            bytes: The packet.
        """
        name = topic_name.encode('ascii')
        packet = bytes([83]) + struct.pack('H', topic_id) + bytes([len(name)]) + name
        packet = packet + bytes([len(values)]) + self.values(values)
        packet = packet + b'\x00\x00' + struct.pack('>H', 1) + bytes([2])
        return packet + bytes([3]) + b'NSE' + bytes([1]) + b'-' + bytes([1]) + b'-'

    def update(self, topic_id, values):
        """An update packet carrying positional values for a topic id.

        Args:
            topic_id (int): The topic id.
            values (list): The positional values.

        Returns:
            bytes: The packet.
        """
        return bytes([85]) + struct.pack('H', topic_id) + bytes([len(values)]) + self.values(values)

    def datafeed(self, message_number, packets):
        """A data feed response holding packets.

        Args:
            message_number (int): The message number an acknowledgement refers to.
            packets (list): The packets.

        Returns:
            bytes: The frame.
        """
        frame = struct.pack('!H', 0) + bytes([6]) + struct.pack('>I', message_number) + struct.pack('!H', len(packets))
        for packet in packets:
            frame = frame + packet
        return frame


class ExpiredTokenThenRefusedFeedExample:
    """Runs a Fyers quotes socket through an expired token and a refused feed.

    Attributes:
        socket (FyersQuotesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the frames, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.fyers')
        api_module.FyersAPI = StandInFyersAPI
        sys.modules['stock_brokers.api.fyers'] = api_module
        LoginRecord.expired_logins = {
            1,
        }
        fytokens = {
            'NSE:SBIN-EQ': '10100000003045',
        }
        sys.modules['requests'] = StandInRequests(fytokens)
        responses = HsmResponses()
        plans = [
            {
                'frames': [
                    responses.auth_response(False, 0),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        websocket_module.when_finished = self.do_nothing
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('fyers.quotes')
        symbols = [
            'NSE:SBIN-EQ',
        ]
        self.socket = FyersQuotesSocket('socket_0', symbols, FyersSession(logger), self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0

    def do_nothing(self):
        """Stands in for closing the socket, which this program leaves to the socket giving up.

        Returns:
            None: This method returns nothing.
        """

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket built.

        Args:
            ticks (list): The normalized ticks from one data message.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            change = tick['change']
            if change is not None:
                change = round(change, 4)
            print(f"Tick {tick['id']} in {tick['mode']} mode")
            print(f"  last_price={tick['last_price']} volume={tick['volume']} change={change}")
            print(f"  ohlc={tick['ohlc']} exchange_timestamp={tick['exchange_timestamp']}")
            if tick['depth']['buy']:
                print(f"  best bid={tick['depth']['buy'][0]} best offer={tick['depth']['sell'][0]}")

    def run(self):
        """Runs the socket's own reconnect loop until it gives up.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    ExpiredTokenThenRefusedFeedExample().run()
