"""Joins Wisdom Capital's XTS interactive namespace and prints the order and position events it hands on.

`WisdomCapitalOrderUpdatesSocket` joins the interactive namespace with the token every Wisdom Capital process shares, and the user id read from that token's JWT payload, adding `apiType=INTERACTIVE` so XTS pushes the account's order, trade and position events. It hands on an order event's orders and a position event's positions, each exactly as XTS sent them, and passes over a trade event because the order event that follows carries the fill. It answers a server ping `2` with `3`.

This program scripts one connection delivering an open order, a trade, a position, a server ping and the order filled. No real socket or HTTPS request is made: a stand-in `urllib3` package answers the Engine.IO handshake, a stand-in `websocket` package plays the frames and prints what the socket sends, and a stand-in `stock_brokers.api.wisdom_capital` module lets the real `WisdomCapitalInteractiveSession` supply a JWT token without logging in.

Notice that the trade event leaves no line, and that orders and positions reach the callback in separate calls.

Run it from the project root:

    python examples/stock_brokers/websockets/wisdom_capital/WisdomCapitalOrderUpdatesSocket/example_1_orders_positions_and_trades.py
"""

import base64
import json
import logging
import sys
import types

from stock_brokers.websockets.wisdom_capital import (
    WisdomCapitalInteractiveSession,
    WisdomCapitalOrderUpdatesSocket,
)


class LoginRecord:
    """The Wisdom Capital login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        market_data_token (str | None): The market data token in force now.
        interactive_user_id (str | None): The user id inside the interactive token in force now.
        interactive_session (str | None): The session inside the interactive token in force now.
        login_count (int): How many interactive logins the stand-in API has made.
        market_data_logins (int): How many market data logins the stand-in API has made.
        market_data_fails (bool): Whether the market data login fails.
    """

    market_data_token = None
    interactive_user_id = 'WC0001'
    interactive_session = None
    login_count = 0
    market_data_logins = 0
    market_data_fails = False


class StandInWisdomCapitalAPI:
    """A stand-in for `WisdomCapitalAPI` whose construction is a pretend login to both XTS applications.

    Attributes:
        market_data_session_error (Exception | None): The market data login failure, recorded rather than raised, as the real class does.
    """

    def __init__(self):
        """Logs in, which here only issues numbered tokens.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.interactive_session = f'interactive-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self.market_data_session_error = None
        if LoginRecord.market_data_fails:
            self.market_data_session_error = RuntimeError('the market data login was refused: Invalid secret key')
        elif LoginRecord.market_data_token is None:
            self.log_in_to_market_data()

    def log_in_to_market_data(self):
        """Issues the next numbered market data token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.market_data_logins = LoginRecord.market_data_logins + 1
        LoginRecord.market_data_token = f'market-data-token-{LoginRecord.market_data_logins}'

    def _current_login(self):
        """The interactive login in force now, its token a JWT carrying the user id as XTS signs it.

        Returns:
            dict: The access token.
        """
        if LoginRecord.interactive_session is None:
            return {
                'access_token': None,
            }
        claims = {
            'session': LoginRecord.interactive_session,
        }
        if LoginRecord.interactive_user_id is not None:
            claims['userID'] = LoginRecord.interactive_user_id
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        return {
            'access_token': f'header.{payload}.signature',
        }

    def market_data_session(self):
        """The market data token and user id in force now.

        Returns:
            dict: `access_token` and `user_id`.
        """
        return {
            'access_token': LoginRecord.market_data_token,
            'user_id': 'WCMD01',
        }

    def replace_market_data_session(self, stale_access_token=None):
        """Logs in to market data again, unless the token in force is no longer the stale one.

        Args:
            stale_access_token (str | None): The token that was refused.

        Returns:
            dict: The market data session now in force.
        """
        if LoginRecord.market_data_token == stale_access_token:
            self.log_in_to_market_data()
            print(f'Stand-in market data login issued {LoginRecord.market_data_token}')
        else:
            print('The market data token was already replaced; no login.')
        return self.market_data_session()


class PinnedResponse:
    """A stand-in for the `urllib3` response of one XTS request.

    Attributes:
        status (int): The HTTP status.
        data (bytes): The body.
    """

    def __init__(self, status, text):
        """Keeps the answer.

        Args:
            status (int): The HTTP status.
            text (str): The body as text.

        Returns:
            None: This method returns nothing.
        """
        self.status = status
        self.data = text.encode()


class PinnedPool:
    """A stand-in for `urllib3.HTTPSConnectionPool` that answers from a shared script.

    Attributes:
        answers (list): The answers still to give, shared by every pool.
    """

    def __init__(self, answers):
        """Keeps the shared answers.

        Args:
            answers (list): The answers still to give, shared by every pool.

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers

    def request(self, method, path, body=None, headers=None, timeout=None):
        """Prints the request and gives the next scripted answer.

        Args:
            method (str): The HTTP method.
            path (str): The path, with its query string.
            body (str | None): The JSON body.
            headers (dict | None): The request headers.
            timeout (int | None): The request timeout in seconds.

        Returns:
            PinnedResponse: The answer.
        """
        shown = path.split('?')[0]
        if body is not None:
            code = json.loads(body).get('xtsMessageCode')
            shown = f'{shown} for message code {code}'
        answer = self.answers.pop(0)
        print(f'HTTPS {method} {shown}: HTTP {answer.status}')
        return answer


class StandInUrllib3:
    """A stand-in for the `urllib3` package whose pools answer from one script.

    Attributes:
        answers (list): The answers, in the order requests are made.
    """

    def __init__(self, answers):
        """Keeps the answers.

        Args:
            answers (list): The answers, in the order requests are made.

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers

    def HTTPSConnectionPool(self, host, port, assert_fingerprint=None):
        """Builds a pool, with the same signature as the real class.

        Args:
            host (str): The host.
            port (int): The port.
            assert_fingerprint (str | None): The certificate pin.

        Returns:
            PinnedPool: The pool.
        """
        return PinnedPool(self.answers)


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
        plan (dict): Either a `refuse_with` status or a list of `frames`, where a frame may also be a function to call at that point.
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
        print(f"Connecting to {self.url.split('?')[0]} with Engine.IO session {self.url.split('sid=')[1].split('&')[0]}")
        if 'refuse_with' in self.plan:
            self.handlers['on_error'](self, HandshakeRefused(self.plan['refuse_with']))
            self.handlers['on_close'](self, None, None)
            return
        self.handlers['on_open'](self)
        for frame in self.plan['frames']:
            if self.closed:
                break
            if callable(frame):
                frame()
                continue
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


class OrdersPositionsAndTradesExample:
    """Runs the Wisdom Capital order update socket against one scripted connection.

    Attributes:
        socket (WisdomCapitalOrderUpdatesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the answers, the frames, the stand-ins, the session and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.wisdom_capital')
        api_module.WisdomCapitalAPI = StandInWisdomCapitalAPI
        sys.modules['stock_brokers.api.wisdom_capital'] = api_module
        sys.modules['urllib3'] = StandInUrllib3([
            self.handshake_answer('engine-session-1'),
        ])
        trade = [
            'trade',
            json.dumps({
                'AppOrderID': 1100012345,
                'LastTradedQuantity': 10,
            }),
        ]
        position = [
            'position',
            {
                'TradingSymbol': 'INFY',
                'Quantity': 10,
            },
        ]
        plans = [
            {
                'frames': [
                    '3probe',
                    self.order_event('New', 0),
                    '42' + json.dumps(trade),
                    '42' + json.dumps(position),
                    '2',
                    self.order_event('Filled', 10),
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('wisdom_capital.orders')
        self.socket = WisdomCapitalOrderUpdatesSocket(WisdomCapitalInteractiveSession(logger), self.print_updates, logger)
        websocket_module.when_finished = self.socket.close

    def handshake_answer(self, session_id):
        """An Engine.IO polling handshake answer, framed with its length prefix as XTS sends it.

        Args:
            session_id (str): The Engine.IO session id.

        Returns:
            PinnedResponse: The answer.
        """
        handshake = {
            'sid': session_id,
            'upgrades': [
                'websocket',
            ],
            'pingInterval': 25000,
            'pingTimeout': 20000,
        }
        text = json.dumps(handshake)
        return PinnedResponse(200, f'{len(text) + 1}:0{text}2:40')

    def order_event(self, status, filled_quantity):
        """A socket.io order event for an INFY buy, its payload a JSON string as XTS sends it.

        Args:
            status (str): XTS's order status.
            filled_quantity (int): How much has filled.

        Returns:
            str: The frame.
        """
        order = {
            'AppOrderID': 1100012345,
            'OrderStatus': status,
            'TradingSymbol': 'INFY',
            'OrderSide': 'BUY',
            'OrderQuantity': 10,
            'CumulativeQuantity': filled_quantity,
        }
        event = [
            'order',
            json.dumps(order),
        ]
        return '42' + json.dumps(event)

    def print_updates(self, orders, positions, received_at):
        """Prints each order and position the socket handed on.

        Args:
            orders (list): The event's orders, exactly as XTS sent them.
            positions (list): The event's positions, exactly as XTS sent them.
            received_at (datetime.datetime): When the event arrived, which is not printed.

        Returns:
            None: This method returns nothing.
        """
        for order in orders:
            print(f"Order {order['AppOrderID']} {order['OrderStatus']}: {order['OrderSide']} {order['CumulativeQuantity']} of {order['OrderQuantity']} {order['TradingSymbol']}")
        for position in positions:
            print(f"Position {position['TradingSymbol']}: net quantity {position['Quantity']}")

    def run(self):
        """Runs the socket's own reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    OrdersPositionsAndTradesExample().run()
