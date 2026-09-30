"""Runs Stoxkart's order socket through authentication, its heartbeat and a frame of order updates.

`StoxkartOrderSocket` first posts to Stoxkart's websocket authentication endpoint with the client code, the access token and the api key, and gets back a RequestId. It then opens `wss://openapi-v2.stoxkart.com/websocket/v2/connect` with that RequestId, sends `{"type": "heartbeat"}` as Stoxkart's website does, and hands each text frame's messages on exactly as sent, logging each one. Like the quote stream it reads a synchronous connection in a loop of its own.

This program scripts one connection delivering a JSON list of two order messages and a frame that is not JSON. No real socket or HTTP request is made: a stand-in `requests` package answers the authentication, a stand-in `websocket` package's `create_connection` returns a scripted connection, which sets the socket's `stop` event once its frames have run out, and a stand-in `stock_brokers.api.stoxkart` module lets the real `StoxkartSession` supply the headers without logging in.

Notice the RequestId in the socket URL, the heartbeat, that both messages reach the callback in one call, and that `run` returns 0 once stopped.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartOrderSocket/example_1_authenticate_and_read_updates.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.stoxkart import (
    StoxkartOrderSocket,
    StoxkartSession,
)


class LoginRecord:
    """The Stoxkart login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInStoxkartAPI:
    """A stand-in for `StoxkartAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'stoxkart-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'ucc_code': 'SK12345',
            'api_key': 'stoxkart-api-key',
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


class AuthenticateResponse:
    """A stand-in for the `requests` response of Stoxkart's websocket authentication.

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
    """A stand-in for the `requests` package that answers websocket authentications in turn.

    Attributes:
        refusals (int): How many of the first requests to refuse with `AuthorizationError`.
        request_count (int): How many requests have been answered.
    """

    def __init__(self, refusals):
        """Keeps how many requests to refuse.

        Args:
            refusals (int): How many of the first requests to refuse with `AuthorizationError`.

        Returns:
            None: This method returns nothing.
        """
        self.refusals = refusals
        self.request_count = 0

    def post(self, url, headers, timeout):
        """Answers one authentication request.

        Args:
            url (str): The endpoint.
            headers (dict): The request headers, carrying the access token.
            timeout (int): The request timeout in seconds.

        Returns:
            AuthenticateResponse: The answer.
        """
        self.request_count = self.request_count + 1
        print(f"Authenticating with {headers['x-access-token']}")
        if self.request_count <= self.refusals:
            body = {
                'code': 'AuthorizationError',
                'message': 'Invalid access token',
            }
            return AuthenticateResponse(401, body)
        body = {
            'data': {
                'RequestId': f'request-{self.request_count}',
            },
        }
        return AuthenticateResponse(200, body)


class ReceiveTimeout(Exception):
    """A stand-in for `websocket.WebSocketTimeoutException`: nothing arrived within the receive timeout."""


class FrameOpcodes:
    """The websocket frame opcodes the Stoxkart streams compare against, as `websocket.ABNF` holds them.

    Attributes:
        OPCODE_TEXT (int): A text frame.
        OPCODE_BINARY (int): A binary frame.
        OPCODE_CLOSE (int): A close frame.
    """

    OPCODE_TEXT = 1
    OPCODE_BINARY = 2
    OPCODE_CLOSE = 8


class ScriptedSynchronousConnection:
    """A stand-in for a synchronous `websocket.WebSocket` that returns scripted frames from `recv_data`.

    Attributes:
        frames (list): Pairs of an opcode and the frame's bytes, in the order they arrive.
        when_empty (callable | None): Called once the last frame has been read, to stop the stream.
    """

    def __init__(self, frames, when_empty):
        """Keeps the frames.

        Args:
            frames (list): Pairs of an opcode and the frame's bytes, in the order they arrive.
            when_empty (callable | None): Called once the last frame has been read, to stop the stream.

        Returns:
            None: This method returns nothing.
        """
        self.frames = frames
        self.when_empty = when_empty

    def send_binary(self, data):
        """Prints a binary request the stream sends.

        Args:
            data (bytes): The request.

        Returns:
            None: This method returns nothing.
        """
        print(f'Sent binary request with code {data[0]} and {len(data)} bytes')

    def send(self, data):
        """Prints a text message the stream sends.

        Args:
            data (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'Sent: {data}')

    def recv_data(self):
        """Returns the next scripted frame, or times out once they have run out.

        Returns:
            tuple: The opcode and the frame's bytes.

        Raises:
            ReceiveTimeout: When no scripted frame is left.
        """
        if not self.frames:
            raise ReceiveTimeout()
        frame = self.frames.pop(0)
        if not self.frames and self.when_empty is not None:
            self.when_empty()
        return frame

    def close(self):
        """Accepts the stream's request to close.

        Returns:
            None: This method returns nothing.
        """


class ScriptedSynchronousModule:
    """A stand-in for the `websocket` package that hands out scripted synchronous connections in turn.

    Attributes:
        plans (list): Each connection's frames, in the order the stream connects.
        when_finished (callable | None): Called after the last connection's last frame, to stop the stream.
        ABNF (FrameOpcodes): The frame opcodes.
        WebSocketTimeoutException (type): The error `recv_data` raises when nothing arrived.
    """

    def __init__(self, plans):
        """Keeps the plans.

        Args:
            plans (list): Each connection's frames, in the order the stream connects.

        Returns:
            None: This method returns nothing.
        """
        self.plans = plans
        self.when_finished = None
        self.ABNF = FrameOpcodes()
        self.WebSocketTimeoutException = ReceiveTimeout

    def create_connection(self, url, timeout):
        """Opens the next scripted connection.

        Args:
            url (str): The socket URL.
            timeout (int): The receive timeout in seconds.

        Returns:
            ScriptedSynchronousConnection: The connection.
        """
        print(f'Connecting to {url}')
        frames = self.plans.pop(0)
        when_empty = None
        if not self.plans:
            when_empty = self.when_finished
        return ScriptedSynchronousConnection(frames, when_empty)


class AuthenticateAndReadUpdatesExample:
    """Runs the Stoxkart order socket against one scripted connection.

    Attributes:
        socket (StoxkartOrderSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the frames, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.stoxkart')
        api_module.StoxkartAPI = StandInStoxkartAPI
        sys.modules['stock_brokers.api.stoxkart'] = api_module
        sys.modules['requests'] = StandInRequests(0)
        updates = [
            {
                'order_id': 'SK2609250001',
                'status': 'OPEN',
                'symbol': 'INFY',
            },
            {
                'order_id': 'SK2609250001',
                'status': 'COMPLETE',
                'symbol': 'INFY',
            },
        ]
        plans = [
            [
                (
                    1,
                    json.dumps(updates).encode(),
                ),
                (
                    1,
                    b'connected',
                ),
            ],
        ]
        websocket_module = ScriptedSynchronousModule(plans)
        sys.modules['websocket'] = websocket_module
        self.socket = StoxkartOrderSocket(StoxkartSession(), self.print_updates, logging.getLogger('stoxkart.orders'))
        websocket_module.when_finished = self.socket.stop.set

    def print_updates(self, messages, received_at):
        """Prints each message the order socket handed on.

        Args:
            messages (list): The frame's messages, exactly as Stoxkart sent them.
            received_at (datetime.datetime): When the frame was read, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        print(f'Callback received {len(messages)} message(s)')

    def run(self):
        """Runs the socket until the scripted connection has delivered everything.

        Returns:
            None: This method returns nothing.
        """
        exit_code = self.socket.run()
        print(f'run returned {exit_code}')


if __name__ == '__main__':
    AuthenticateAndReadUpdatesExample().run()
