"""Receives protobuf orders and positions on Groww's order update stream and prints the decoded dictionaries.

`GrowwOrderUpdatesSocket` obtains a socket JWT and a subscription id, answers the server's INFO with CONNECT, and subscribes the account's equity orders, derivatives orders and derivatives positions subjects, each keyed by the subscription id. Each payload is decoded to a plain dictionary with Groww's own field names, enum fields by name and every field present even when zero.

This program delivers an equity order, a derivatives position and a message on a subject the socket never subscribed, split across two websocket frames. No real socket or HTTP request is made: a stand-in `requests` package answers the socket token request, a stand-in `websocket` package plays the frames and prints the NATS lines the socket sends with the signature replaced by its length, and a stand-in `stock_brokers.api.groww` module lets the real `GrowwSession` supply the access token. The payloads are built with `GrowwMessageClasses`.

Notice the three SUB lines ending in `subscription-77`, that enums such as `orderStatus` arrive by name, and that the unexpected subject is logged and skipped.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwOrderUpdatesSocket/example_1_orders_and_positions.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.groww import (
    GrowwMessageClasses,
    GrowwOrderUpdatesSocket,
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


class OrdersAndPositionsExample:
    """Runs the Groww order update socket against one scripted NATS connection.

    Attributes:
        socket (GrowwOrderUpdatesSocket): The socket being shown.
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
        position_class = GrowwMessageClasses().order_and_position_classes()[1]
        position = position_class()
        position.symbolData.contractId = 'NIFTY26SEP25000CE'
        position.symbolData.displayName = 'NIFTY 25000 Call 30 Sep'
        position.positionInfo.NSE.creditQty = 75
        position.positionInfo.NSE.creditPrice = 12550
        nats = NatsFrames()
        whole = nats.message('stocks/order/updates.apex.subscription-77', self.order_payload(11, 10))
        whole = whole + nats.message('stocks_fo/position/updates.apex.subscription-77', position.SerializeToString())
        stray = nats.message('stocks/order/updates.apex.someone-else', self.order_payload(1, 0))
        plans = [
            {
                'frames': [
                    nats.info(),
                    whole[:30],
                    whole[30:] + stray,
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('groww.orders')
        self.socket = GrowwOrderUpdatesSocket(GrowwSession(logger), self.print_updates, logger)
        websocket_module.when_finished = self.socket.close

    def order_payload(self, status, filled_quantity):
        """A serialized `OrderDetailsBroadCastDto` for an INFY buy.

        Args:
            status (int): Groww's order status number, 1 for acknowledged and 11 for completed.
            filled_quantity (int): How much has filled.

        Returns:
            bytes: The protobuf payload.
        """
        order_class = GrowwMessageClasses().order_and_position_classes()[0]
        broadcast = order_class()
        detail = broadcast.orderDetailUpdateDto
        detail.growwOrderId = 'GMK2609250001'
        detail.qty = 10
        detail.filledQty = filled_quantity
        detail.price = 150000
        detail.orderStatus = status
        detail.exchange = 1
        detail.buySell = 0
        return broadcast.SerializeToString()

    def print_updates(self, orders, positions, received_at):
        """Prints each decoded order and position the socket handed on.

        Args:
            orders (list): The frame's orders, as dictionaries with Groww's field names.
            positions (list): The frame's positions, as dictionaries with Groww's field names.
            received_at (float): The epoch the frame arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        for order in orders:
            detail = order['orderDetailUpdateDto']
            print(f"Order {detail['growwOrderId']} {detail['orderStatus']}: {detail['buySell']} {detail['filledQty']} of {detail['qty']} on {detail['exchange']} at {detail['price']}")
        for position in positions:
            print(f"Position {position['symbolData']['contractId']}: NSE credit quantity {position['positionInfo']['NSE']['creditQty']}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    OrdersAndPositionsExample().run()
