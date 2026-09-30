"""Shows a Wisdom Capital quotes socket replacing a refused market data token and clearing a subscription left from an earlier connection.

XTS refuses a dead market data token at the Engine.IO handshake with an answer mentioning `Invalid Token`. `WisdomCapitalQuotesSocket` takes that as a refused login, and its reconnect loop asks `WisdomCapitalMarketDataSession.replace` for a new token, which the API issues only if nobody replaced the refused one already. Separately, XTS answers a subscription for instruments still subscribed from an earlier connection with `e-session-0002 Instrument Already Subscribed`, whose prefix looks like a refused token; the socket instead drops that subscription with a `PUT` and asks again.

This program's first handshake is refused. The second succeeds, its touchline subscription is refused as already subscribed, then dropped and granted, and the depth subscription is granted. No real socket or HTTPS request is made: stand-in `urllib3` and `websocket` packages play the answers and the frames, and a stand-in `stock_brokers.api.wisdom_capital` module issues numbered market data tokens. The backoff is set to zero seconds.

Notice the market data login between the two handshakes, the `PUT` that drops the stale subscription, and the snapshot tick handed on once the subscription is granted.

Run it from the project root:

    python examples/stock_brokers/websockets/wisdom_capital/WisdomCapitalQuotesSocket/example_2_refused_token_and_stale_subscription.py
"""

import base64
import json
import logging
import sys
import types

from stock_brokers.websockets.wisdom_capital import (
    WisdomCapitalMarketDataSession,
    WisdomCapitalQuotesSocket,
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


class RefusedTokenAndStaleSubscriptionExample:
    """Runs a Wisdom Capital quotes socket through a refused handshake and a stale subscription.

    Attributes:
        socket (WisdomCapitalQuotesSocket): The socket being shown.
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
        refused = {
            'type': 'error',
            'code': 'e-session-0001',
            'description': 'Invalid Token',
        }
        already_subscribed = {
            'type': 'error',
            'code': 'e-session-0002',
            'description': 'Instrument Already Subscribed !',
        }
        success = {
            'type': 'success',
        }
        answers = [
            PinnedResponse(400, json.dumps(refused)),
            self.handshake_answer('engine-session-2'),
            PinnedResponse(400, json.dumps(already_subscribed)),
            PinnedResponse(200, json.dumps(success)),
            self.subscription_answer([
                self.touchline(2950.5),
            ]),
            self.subscription_answer([]),
        ]
        sys.modules['urllib3'] = StandInUrllib3(answers)
        plans = [
            {
                'frames': [
                    '3probe',
                ],
            },
        ]
        websocket_module = ScriptedWebsocketModule(plans)
        sys.modules['websocket'] = websocket_module
        logger = logging.getLogger('wisdom_capital.quotes')
        tokens = [
            '1:2885',
        ]
        session = WisdomCapitalMarketDataSession(logger)
        self.socket = WisdomCapitalQuotesSocket('socket_0', tokens, {}, session, self.print_ticks, logger)
        self.socket.MIN_BACKOFF_SECONDS = 0
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

    def touchline(self, last_price):
        """An XTS touchline for NSE RELIANCE (segment 1, instrument 2885), with XTS's misspelt last traded quantity.

        Args:
            last_price (float): The last traded price.

        Returns:
            dict: The touchline.
        """
        return {
            'ExchangeSegment': 1,
            'ExchangeInstrumentID': 2885,
            'LastTradedPrice': last_price,
            'LastTradedQunatity': 25,
            'TotalTradedQuantity': 1204500,
            'AverageTradedPrice': 2949.0,
            'Open': 2930.0,
            'High': 2960.0,
            'Low': 2925.0,
            'Close': 2910.0,
            'LastTradedTime': 1790311528 - 315513000,
            'ExchangeTimeStamp': 1790311529 - 315513000,
            'BidInfo': {
                'Size': 100,
                'Price': 2950.0,
                'TotalOrders': 3,
            },
            'AskInfo': {
                'Size': 120,
                'Price': 2950.5,
                'TotalOrders': 4,
            },
        }

    def depth_event(self, last_price):
        """A socket.io market depth event whose quote nests its touchline, with padded zero rows.

        Args:
            last_price (float): The last traded price.

        Returns:
            str: The frame.
        """
        bids = []
        asks = []
        for level in range(5):
            bids.append({
                'Size': 100 + level,
                'Price': 2950.0 - level * 0.05,
                'TotalOrders': 3,
            })
            asks.append({
                'Size': 200 + level,
                'Price': 2951.0 + level * 0.05,
                'TotalOrders': 4,
            })
        bids.append({
            'Size': 0,
            'Price': 0,
            'TotalOrders': 0,
        })
        quote = {
            'ExchangeSegment': 1,
            'ExchangeInstrumentID': 2885,
            'Bids': bids,
            'Asks': asks,
            'Touchline': self.touchline(last_price),
        }
        event = [
            '1502-json-full',
            json.dumps(quote),
        ]
        return '42' + json.dumps(event)

    def subscription_answer(self, quotes):
        """A successful subscription answer carrying the current snapshot as JSON strings.

        Args:
            quotes (list): The quotes in the snapshot.

        Returns:
            PinnedResponse: The answer.
        """
        encoded = []
        for quote in quotes:
            encoded.append(json.dumps(quote))
        answer = {
            'type': 'success',
            'result': {
                'listQuotes': encoded,
            },
        }
        return PinnedResponse(200, json.dumps(answer))

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket handed on.

        Args:
            ticks (list): The ticks.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            change = tick['change']
            if change is not None:
                change = round(change, 4)
            print(f"Tick {tick['id']} ({tick['instrument_token']}) on {tick['exchange']} in {tick['mode']} mode")
            print(f"  last_price={tick['last_price']} last_quantity={tick['last_quantity']} volume={tick['volume']} change={change}")
            print(f"  last_trade_time={tick['last_trade_time']} exchange_timestamp={tick['exchange_timestamp']}")
            if tick['depth']['buy']:
                print(f"  best bid={tick['depth']['buy'][0]} best offer={tick['depth']['sell'][0]} levels={len(tick['depth']['buy'])}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')
        print(f'Market data logins: {LoginRecord.market_data_logins}')


if __name__ == '__main__':
    RefusedTokenAndStaleSubscriptionExample().run()
