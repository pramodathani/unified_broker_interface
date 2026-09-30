"""Runs a Groww quotes socket through the socket token, the NATS handshake, and one price and one depth message.

`GrowwQuotesSocket` speaks NATS over a websocket. Before connecting it generates a fresh ed25519 key pair and exchanges its public key for a short-lived socket JWT. When the server opens with an INFO line carrying a nonce, the socket answers CONNECT with the JWT and the signed nonce, then PING, then one SUB for the price subject and one for the depth subject of each instrument. Payloads are protobuf `StocksSocketResponseProtoDto` messages; price and depth arrive separately and are merged per instrument, prices in paise are divided into rupees, and quantities arrive as doubles and are rounded.

This program subscribes NSE token 2885 and delivers a price message and a depth message in one websocket frame. No real socket or HTTP request is made: a stand-in `requests` package answers the socket token request, a stand-in `websocket` package plays the frames and prints the NATS lines the socket sends with the signature replaced by its length, because the key pair is fresh on every run, and a stand-in `stock_brokers.api.groww` module lets the real `GrowwSession` supply the access token without logging in. The payloads are built with `GrowwMessageClasses`.

Notice the two SUB lines, that the first tick is a quote and the second, after the depth message, is full with both, and that the instrument takes the name `NSE:RELIANCE` from the payload's symbol because the program gave it none.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwQuotesSocket/example_1_price_and_depth_over_nats.py
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


class PriceAndDepthOverNatsExample:
    """Runs a Groww quotes socket against one scripted NATS connection.

    Attributes:
        socket (GrowwQuotesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the payloads, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.groww')
        api_module.GrowwAPI = StandInGrowwAPI
        sys.modules['stock_brokers.api.groww'] = api_module
        sys.modules['requests'] = StandInRequests([
            200,
        ])
        response_class = GrowwMessageClasses().stocks_response_class()
        price = response_class()
        price.symbol = 'RELIANCE'
        price.stockLivePrice.tsInMillis = 1790311529000
        price.stockLivePrice.ltp = 295050
        price.stockLivePrice.open = 293000
        price.stockLivePrice.high = 296000
        price.stockLivePrice.low = 292500
        price.stockLivePrice.close = 291000
        price.stockLivePrice.volume = 1204500.0
        depth = response_class()
        depth.symbol = 'RELIANCE'
        depth.stocksMarketDepth.buyBook[1].price = 295000
        depth.stocksMarketDepth.buyBook[1].qty = 100.0
        depth.stocksMarketDepth.sellBook[1].price = 295100
        depth.stocksMarketDepth.sellBook[1].qty = 120.0
        nats = NatsFrames()
        frame = nats.message('/ld/eq/nse/price_detailed.2885', price.SerializeToString())
        frame = frame + nats.message('/ld/eq/nse/book.2885', depth.SerializeToString())
        plans = [
            {
                'frames': [
                    nats.info(),
                    frame,
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('groww.quotes')
        tokens = [
            'NSE|CASH|2885',
        ]
        self.names = {}
        self.socket = GrowwQuotesSocket('socket_0', tokens, self.names, GrowwSession(logger), self.print_ticks, logger)
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
        print(f'Names learned: {self.names}')
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    PriceAndDepthOverNatsExample().run()
