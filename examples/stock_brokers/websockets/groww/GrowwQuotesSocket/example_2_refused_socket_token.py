"""Shows a Groww quotes socket logging in again when its socket token is refused, then answering a server PING.

A dead Groww access token is discovered before any websocket opens: the socket token endpoint answers HTTP 401 or 403. `GrowwQuotesSocket` takes that as a refused login, and its reconnect loop asks the shared `GrowwSession` to log in again, skipping the login when another socket or process already replaced the token. Once connected, the socket answers a NATS `PING` from the server with `PONG`.

This program's first socket token request is refused with HTTP 403 and the second succeeds. The second connection opens with INFO, then the server sends a PING and an index value for the NIFTY index (token 26000 on the NSE cash segment). No real socket or HTTP request is made: stand-in `requests` and `websocket` packages play the answers and frames, and a stand-in `stock_brokers.api.groww` module counts each `GrowwAPI` construction as one login. The backoff is set to zero seconds.

Notice that the second token request carries the new access token, the PONG line, and that an index tick has a last price but no open, high, low or close.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwQuotesSocket/example_2_refused_socket_token.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.groww import (
    GrowwMessageClasses,
    GrowwQuotesSocket,
    GrowwSession,
)


class LoginRecord:
    """The Groww login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInGrowwAPI:
    """A stand-in for `GrowwAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'groww-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'api_key': 'groww-api-key',
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


class SocketTokenResponse:
    """A stand-in for the `requests` response of Groww's socket token endpoint.

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

    def raise_for_status(self):
        """Does nothing, because every scripted answer that reaches it succeeded.

        Returns:
            None: This method returns nothing.
        """


class StandInRequests:
    """A stand-in for the `requests` package that answers socket token requests in turn.

    Attributes:
        statuses (list): The HTTP status of each answer, in order.
    """

    def __init__(self, statuses):
        """Keeps the scripted statuses.

        Args:
            statuses (list): The HTTP status of each answer, in order.

        Returns:
            None: This method returns nothing.
        """
        self.statuses = statuses

    def post(self, url, headers, json, timeout):
        """Answers one socket token request.

        Args:
            url (str): The endpoint.
            headers (dict): The request headers, carrying the access token.
            json (dict): The request body with the public key.
            timeout (int): The request timeout in seconds.

        Returns:
            SocketTokenResponse: The answer.
        """
        status = self.statuses.pop(0)
        print(f"Socket token request with {headers['Authorization']} for a key starting {json['socketKey'][0]}: HTTP {status}")
        if status != 200:
            body = {
                'message': 'Unauthorized',
            }
            return SocketTokenResponse(status, body)
        body = {
            'payload': {
                'token': 'socket-jwt',
                'subscriptionId': 'subscription-77',
            },
        }
        return SocketTokenResponse(status, body)


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
        text = data.rstrip('\r\n')
        if text.startswith('CONNECT '):
            connect = json.loads(text[len('CONNECT '):])
            connect['sig'] = f"<{len(connect['sig'])} character signature>"
            text = f'CONNECT {json.dumps(connect)}'
        print(f'Sent: {text}')

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


class NatsFrames:
    """Builds the NATS lines Groww's server sends over the websocket."""

    def info(self):
        """The INFO line the server opens with, carrying a nonce.

        Returns:
            str: The line.
        """
        info = {
            'server_id': 'groww-nats',
            'nonce': 'example-nonce',
            'headers': True,
        }
        return f'INFO {json.dumps(info)}\r\n'

    def message(self, subject, payload):
        """A MSG line followed by its payload.

        Args:
            subject (str): The subject the message arrived on.
            payload (bytes): The protobuf payload.

        Returns:
            bytes: The message.
        """
        return f'MSG {subject} 1 {len(payload)}\r\n'.encode() + payload + b'\r\n'


class RefusedSocketTokenExample:
    """Runs a Groww quotes socket through a refused token and a good connection.

    Attributes:
        socket (GrowwQuotesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the payload, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.groww')
        api_module.GrowwAPI = StandInGrowwAPI
        sys.modules['stock_brokers.api.groww'] = api_module
        sys.modules['requests'] = StandInRequests([
            403,
            200,
        ])
        index = GrowwMessageClasses().stocks_response_class()()
        index.stocksLiveIndices.value = 2515065
        index.stocksLiveIndices.tsInMillis = 1790311529000
        nats = NatsFrames()
        plans = [
            {
                'frames': [
                    nats.info(),
                    'PING\r\n',
                    nats.message('/ld/eq/nse/price_detailed.26000', index.SerializeToString()),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('groww.quotes')
        tokens = [
            'NSE|CASH|26000',
        ]
        names = {
            'NSE|CASH|26000': 'NSE:NIFTY',
        }
        self.socket = GrowwQuotesSocket('socket_0', tokens, names, GrowwSession(logger), self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
        websocket_module.when_finished = self.socket.close

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
            print(f"  last_price={tick['last_price']} volume={tick['volume']} change={change} exchange_timestamp={tick['exchange_timestamp']}")
            print(f"  ohlc={tick['ohlc']}")
            print(f"  depth={tick['depth']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    RefusedSocketTokenExample().run()
