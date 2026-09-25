"""The Wisdom Capital quotes and order updates sockets, driven through scripted XTS connections."""

import base64
import json
import types

from stock_brokers.websockets import wisdom_capital as wisdom_capital_websockets
from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/wisdom_capital/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/wisdom_capital/orders/websocket_order_details'

HANDSHAKE = '96:0{"sid":"engine-session-1","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":20000}2:40'
HANDSHAKE_WITHOUT_LIMITS = '40:0{"sid":"engine-session-2","upgrades":[]}2:40'
XTS_TIME = 1474796129


class StubWisdomCapitalAPI(harness.StubBrokerAPI):
    """A stand-in for `WisdomCapitalAPI`, with the market data session calls the quotes socket makes and the JWT interactive token the order socket reads.

    Attributes:
        failed_market_data_logins (set): The login numbers whose market data login fails without raising, as the real class records it.
    """

    failed_market_data_logins = set()

    def __init__(self):
        """Logs in, recording a market data failure the scenario scripts rather than raising it.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the ledger scripts this login to fail.
        """
        super().__init__()
        self.market_data_session_error = None
        if harness.StubBrokerAPI.logins.login_count in StubWisdomCapitalAPI.failed_market_data_logins:
            self.market_data_session_error = RuntimeError('Scripted market data login failure')

    def _current_login(self):
        """The interactive login in force now, its token a JWT carrying the user id as XTS signs it.

        Returns:
            dict | None: The access token in force, or None before any login.
        """
        token = harness.StubBrokerAPI.logins.current_token
        if token is None:
            return {
                'access_token': None,
            }
        return {
            'access_token': self.jwt(token),
        }

    def jwt(self, token):
        """Wraps a ledger token in an unsigned JWT whose payload carries `userID`.

        Args:
            token (str): The ledger's token.

        Returns:
            str: The JWT.
        """
        header = self.encode({'alg': 'none'})
        payload = self.encode({'userID': 'WC0001', 'session': token})
        return f'{header}.{payload}.signature'

    def encode(self, value):
        """Base64url-encodes a JSON value without padding, as a JWT segment.

        Args:
            value (dict): The value.

        Returns:
            str: The segment.
        """
        return base64.urlsafe_b64encode(json.dumps(value).encode('utf-8')).decode('ascii').rstrip('=')

    def market_data_session(self):
        """The market data token and user id in force now.

        Returns:
            dict: `access_token` and `user_id`.
        """
        return {
            'access_token': harness.StubBrokerAPI.logins.current_token,
            'user_id': 'WCMD01',
        }

    def replace_market_data_session(self, stale_access_token=None):
        """Logs in to market data again, unless the token in force is no longer the stale one.

        Args:
            stale_access_token (str | None): The token that was refused.

        Returns:
            dict: The market data session now in force.

        Raises:
            RuntimeError: When the ledger scripts the login to fail.
        """
        ledger = harness.StubBrokerAPI.logins
        ledger.event_log.add('replace_market_data_session', stale_access_token)
        if ledger.current_token == stale_access_token:
            ledger.log_in()
        return self.market_data_session()


class WisdomCapitalFeedCases:
    """Every Wisdom Capital scenario, and how each socket is built the way its script builds it.

    Attributes:
        loader (harness.ScriptLoader): Loads the two scripts.
    """

    def __init__(self, loader):
        """Keeps the script loader.

        Args:
            loader (harness.ScriptLoader): Loads the two scripts.

        Returns:
            None: This method returns nothing.
        """
        self.loader = loader

    def stub_modules(self, context):
        """The modules replaced while a Wisdom Capital scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        StubWisdomCapitalAPI.failed_market_data_logins = set()
        api_module = types.ModuleType('stock_brokers.api.wisdom_capital')
        api_module.WisdomCapitalAPI = StubWisdomCapitalAPI
        return {
            'stock_brokers.api.wisdom_capital': api_module,
            'urllib3': context.urllib3_module,
        }

    def attribute_patches(self, context):
        """The attributes replaced while a scenario runs; none for this broker.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            list: Tuples of an object, an attribute name and its value.
        """
        return []

    def datetime_holders(self):
        """The modules whose `datetime` name is frozen while a scenario runs.

        Returns:
            list: The modules.
        """
        return [
            self.loader.load(ORDERS_SCRIPT),
            wisdom_capital_websockets,
        ]

    def build_quotes_socket(self, context, tokens, names):
        """Builds a quotes socket the way `bin/wisdom_capital/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The `SEGMENT:EXCHANGEINSTRUMENTID` tokens to subscribe to.
            names (dict): Tokens to instrument names.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = wisdom_capital_websockets.WisdomCapitalMarketDataSession(context.logger)
        store = script.WisdomCapitalQuotesStore(context.redis)
        socket = wisdom_capital_websockets.WisdomCapitalQuotesSocket(
            'socket_0',
            tokens,
            names,
            session,
            store.write_ticks,
            context.logger,
        )
        context.use_instant_waits(socket)
        return socket

    def build_order_socket(self, context):
        """Builds an order updates socket the way `bin/wisdom_capital/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        session = wisdom_capital_websockets.WisdomCapitalInteractiveSession(context.logger)
        store = script.WisdomCapitalOrderUpdatesStore(context.redis, context.logger)
        socket = wisdom_capital_websockets.WisdomCapitalOrderUpdatesSocket(session, store.write_updates, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every Wisdom Capital scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        return [
            (
                'wisdom_capital.quotes.every_message_shape',
                [
                    self.every_quote_message_connection(),
                ],
                set(),
                self.run_quotes_every_message_shape,
            ),
            (
                'wisdom_capital.quotes.subscription_refused_replaces_the_token',
                [
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes_subscription_refused,
            ),
            (
                'wisdom_capital.quotes.handshake_refused_replaces_the_token',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_handshake_refused,
            ),
            (
                'wisdom_capital.quotes.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', '3probe'),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_token_replaced_elsewhere,
            ),
            (
                'wisdom_capital.quotes.certificate_does_not_match_the_pin',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_certificate_mismatch,
            ),
            (
                'wisdom_capital.quotes.refused_again_gives_up',
                [],
                set(),
                self.run_quotes_refused_again,
            ),
            (
                'wisdom_capital.quotes.failed_connects_give_up',
                [],
                set(),
                self.run_quotes_failed_connects,
            ),
            (
                'wisdom_capital.quotes.token_replacement_fails',
                [],
                {
                    2,
                },
                self.run_quotes_handshake_refused,
            ),
            (
                'wisdom_capital.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes,
            ),
            (
                'wisdom_capital.quotes.market_data_login_fails',
                [],
                set(),
                self.run_quotes_market_data_login_fails,
            ),
            (
                'wisdom_capital.orders.updates',
                [
                    self.every_order_message_connection(),
                ],
                set(),
                self.run_orders_one_handshake,
            ),
            (
                'wisdom_capital.orders.logout_with_a_replacement_login',
                [
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('call', self.log_in_elsewhere),
                        ('message', '42' + json.dumps(['logout', 'You have been logged out by another user.'])),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders_two_handshakes,
            ),
            (
                'wisdom_capital.orders.logout_without_a_replacement_login',
                [
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('message', '42' + json.dumps(['logout', {'message': 'You have been logged out by another user.'}])),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders_two_handshakes,
            ),
            (
                'wisdom_capital.orders.no_stored_token',
                [
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('call', self.forget_the_token),
                        ('close', None, None),
                    ],
                ],
                set(),
                self.run_orders_one_handshake,
            ),
            (
                'wisdom_capital.orders.handshake_refused_logs_in_again',
                [
                    [
                        ('open',),
                        ('message', '3probe'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders_handshake_refused,
            ),
            (
                'wisdom_capital.orders.certificate_does_not_match_the_pin',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders_certificate_mismatch,
            ),
            (
                'wisdom_capital.orders.refused_again_gives_up',
                [],
                set(),
                self.run_orders_refused_again,
            ),
            (
                'wisdom_capital.orders.failed_connects_give_up',
                [],
                set(),
                self.run_orders_failed_connects,
            ),
            (
                'wisdom_capital.orders.login_again_fails',
                [],
                {
                    2,
                },
                self.run_orders_refused_again,
            ),
            (
                'wisdom_capital.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders,
            ),
        ]

    def every_quote_message_connection(self):
        """One connection carrying every kind of frame the quotes decoder handles.

        Returns:
            list: The scripted steps.
        """
        touchline = {
            'MessageCode': 1501,
            'ExchangeSegment': 2,
            'ExchangeInstrumentID': 35001,
            'Touchline': {
                'LastTradedPrice': 25150.5,
                'LastTradedQunatity': None,
                'LastTradedQuantity': 75,
                'AverageTradedPrice': 25148.1,
                'TotalTradedQuantity': 150000,
                'TotalBuyQuantity': 5400,
                'TotalSellQuantity': 6100,
                'Open': 25100,
                'High': 25200,
                'Low': 25050,
                'Close': 25100,
                'LastTradedTime': XTS_TIME,
                'LastUpdateTime': XTS_TIME + 1,
                'BidInfo': {
                    'Size': 75,
                    'Price': 25150,
                    'TotalOrders': 3,
                },
                'AskInfo': {
                    'Size': 150,
                    'Price': 25151,
                    'TotalOrders': 4,
                },
            },
        }
        no_price = {
            'ExchangeSegment': 1,
            'ExchangeInstrumentID': 11536,
            'Touchline': {
                'Open': 1640,
            },
        }
        both = [
            {
                'ExchangeSegment': 51,
                'ExchangeInstrumentID': 426016,
                'LastTradedPrice': 6123,
                'Close': 6100,
                'OpenInterest': 12000,
                'ExchangeTimeStamp': XTS_TIME,
            },
            {
                'ExchangeSegment': 99,
                'ExchangeInstrumentID': 1,
                'LastTradedPrice': 10,
            },
            {
                'ExchangeSegment': None,
                'ExchangeInstrumentID': 2,
            },
            'not a dictionary',
        ]
        return [
            ('open',),
            ('message', '3probe'),
            ('message', '2'),
            ('message', '42' + json.dumps(['1501-json-full', json.dumps(touchline)])),
            ('message', '42' + json.dumps(['1501-json-full', no_price])),
            ('message', ('42' + json.dumps(['1501-json-full', both])).encode('utf-8')),
            ('message', '42' + json.dumps(['1501-json-full', 'not json'])),
            ('message', '42' + json.dumps(['joined'])),
            ('message', '42[not json'),
            ('message', '40'),
            ('close', 1000, 'normal closure'),
        ]

    def every_order_message_connection(self):
        """One connection carrying every kind of event the order decoder handles.

        Returns:
            list: The scripted steps.
        """
        without_id = self.xts_order('', 'Open')
        without_id['AppOrderID'] = None
        positions = [
            self.xts_position('NET'),
            self.xts_position(None),
            {
                'TradingSymbol': 'NO KEY',
            },
        ]
        return [
            ('open',),
            ('message', '3probe'),
            ('message', '2'),
            ('message', '42' + json.dumps(['order', self.xts_order(1100000001, 'Filled')])),
            ('message', '42' + json.dumps(['order', [self.xts_order(1100000002, 'New'), without_id, 'not a dictionary']])),
            ('message', '42' + json.dumps(['position', json.dumps(positions)])),
            ('message', '42' + json.dumps(['trade', self.xts_order(1100000001, 'Filled')])),
            ('message', '42' + json.dumps(['joined', 'Welcome'])),
            ('message', '42' + json.dumps(['interactive', self.xts_order(1100000003, 'Rejected')]).encode('utf-8').decode('utf-8')),
            ('message', ('42' + json.dumps(['order', 'not json'])).encode('utf-8')),
            ('message', '42[not json'),
            ('message', '42[]'),
            ('message', '40'),
            ('close', 1000, 'normal closure'),
        ]

    def subscription_answer(self, quotes):
        """A successful subscription answer carrying a snapshot.

        Args:
            quotes (list): The snapshot's quotes.

        Returns:
            tuple: The HTTP status and body.
        """
        return (
            200,
            json.dumps({
                'type': 'success',
                'result': {
                    'listQuotes': quotes,
                },
            }),
        )

    def run_quotes_every_message_shape(self, context):
        """Runs a quotes socket whose depth subscription is found already subscribed, dropped and asked again.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        snapshot = {
            'MessageCode': 1502,
            'ExchangeSegment': 1,
            'ExchangeInstrumentID': 2885,
            'Bids': [
                {
                    'Size': 10,
                    'Price': 2950.4,
                    'TotalOrders': 2,
                },
                {
                    'Size': 0,
                    'Price': 0,
                    'TotalOrders': 0,
                },
            ],
            'Asks': [
                {
                    'Size': 12,
                    'Price': 2950.6,
                    'TotalOrders': 1,
                },
            ],
            'Touchline': {
                'LastTradedPrice': 2950.5,
                'Close': 2930,
                'LastTradedTime': XTS_TIME,
            },
        }
        context.urllib3_module.answers = [
            (200, HANDSHAKE),
            self.subscription_answer([json.dumps({'ExchangeSegment': 1, 'ExchangeInstrumentID': 2885, 'LastTradedPrice': 2950.0})]),
            (400, '{"type":"error","code":"e-session-0002","description":"Instrument Already Subscribed !"}'),
            (200, '{"type":"success"}'),
            self.subscription_answer([snapshot]),
            (200, HANDSHAKE_WITHOUT_LIMITS),
        ]
        return self.run_quotes(context)

    def run_quotes_subscription_refused(self, context):
        """Runs a quotes socket whose subscription refuses the token, then one that subscribes after the token is replaced.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (200, HANDSHAKE),
            (400, '{"type":"error","code":"e-session-0007","description":"Invalid Token"}'),
            (200, HANDSHAKE),
            (500, '{"type":"error","description":"Internal server error"}'),
            self.subscription_answer([]),
            (200, HANDSHAKE),
        ]
        return self.run_quotes(context)

    def run_quotes_handshake_refused(self, context):
        """Runs a quotes socket whose Engine.IO handshake refuses the token, then one that connects after it is replaced.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (401, '{"type":"error","code":"e-token-0005","description":"Invalid Token"}'),
            (200, HANDSHAKE),
            (200, HANDSHAKE),
        ]
        return self.run_quotes(context)

    def run_quotes_token_replaced_elsewhere(self, context):
        """Runs a quotes socket whose subscription is refused after another process has already replaced the market data token.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (200, HANDSHAKE),
            (400, '{"type":"error","code":"e-session-0007","description":"Invalid Token"}'),
            (200, HANDSHAKE),
            (200, HANDSHAKE),
        ]
        return self.run_quotes(context)

    def run_quotes_certificate_mismatch(self, context):
        """Runs a quotes socket whose host presents a certificate other than the pinned one.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.websocket_module.peer_certificate = b'not the pinned certificate'
        context.urllib3_module.answers = [
            (200, HANDSHAKE),
            (200, HANDSHAKE),
        ]
        return self.run_quotes(context)

    def run_quotes_refused_again(self, context):
        """Runs a quotes socket whose handshake is refused before and after the token is replaced.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (401, 'e-session-0007 Invalid Token'),
            (401, 'e-session-0007 Invalid Token'),
        ]
        return self.run_quotes(context)

    def run_quotes_failed_connects(self, context):
        """Runs a quotes socket whose handshake keeps failing for reasons other than the token.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = []
        for _ in range(12):
            answers.append((503, 'Service Unavailable'))
        context.urllib3_module.answers = answers
        return self.run_quotes(context)

    def run_quotes_market_data_login_fails(self, context):
        """Builds a quotes socket whose login records a market data failure, which the session raises.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: The error that stopped the socket being built.
        """
        StubWisdomCapitalAPI.failed_market_data_logins = {
            1,
        }
        return self.run_quotes(context)

    def run_quotes(self, context):
        """Builds a quotes socket for three instruments, one named, and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        tokens = [
            '1:2885',
            '2:35001',
            '51:426016',
        ]
        names = {
            '1:2885': 'NSECM:RELIANCE-EQ',
        }
        try:
            socket = self.build_quotes_socket(context, tokens, names)
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }

    def run_orders_one_handshake(self, context):
        """Runs an order socket that connects once and is then closed.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (200, HANDSHAKE),
            (200, HANDSHAKE_WITHOUT_LIMITS),
        ]
        return self.run_orders(context)

    def run_orders_two_handshakes(self, context):
        """Runs an order socket that connects twice and is then closed.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (200, HANDSHAKE),
            (200, HANDSHAKE),
            (200, HANDSHAKE),
        ]
        return self.run_orders(context)

    def run_orders_handshake_refused(self, context):
        """Runs an order socket whose handshake refuses the token, and which connects after logging in again.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (401, '{"type":"error","code":"e-session-0007","description":"Invalid Token"}'),
            (200, HANDSHAKE),
            (200, HANDSHAKE),
        ]
        return self.run_orders(context)

    def run_orders_certificate_mismatch(self, context):
        """Runs an order socket whose host presents a certificate other than the pinned one.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.websocket_module.peer_certificate = b'not the pinned certificate'
        context.urllib3_module.answers = [
            (200, HANDSHAKE),
            (200, HANDSHAKE),
        ]
        return self.run_orders(context)

    def run_orders_refused_again(self, context):
        """Runs an order socket whose handshake is refused before and after logging in again.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        context.urllib3_module.answers = [
            (401, 'e-token invalid'),
            (401, 'e-token invalid'),
        ]
        return self.run_orders(context)

    def run_orders_failed_connects(self, context):
        """Runs an order socket whose handshake keeps failing for reasons other than the token.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = []
        for _ in range(12):
            answers.append((503, 'Service Unavailable'))
        context.urllib3_module.answers = answers
        return self.run_orders(context)

    def run_orders(self, context):
        """Builds an order updates socket and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        try:
            socket = self.build_order_socket(context)
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }

    def log_in_elsewhere(self):
        """Replaces the token as another process logging in would.

        Returns:
            None: This method returns nothing.
        """
        harness.StubBrokerAPI.logins.replace_elsewhere('token-from-another-process')

    def forget_the_token(self):
        """Empties the stored login, as when `last_login` holds no token.

        Returns:
            None: This method returns nothing.
        """
        harness.StubBrokerAPI.logins.replace_elsewhere(None)

    def xts_order(self, order_id, status):
        """An order as XTS pushes it in an `order` event.

        Args:
            order_id (int | str | None): The app order id.
            status (str): XTS's order status.

        Returns:
            dict: The order.
        """
        return {
            'AppOrderID': order_id,
            'ExchangeOrderID': '1100000012345678',
            'OrderStatus': status,
            'CancelRejectReason': '',
            'ExchangeSegment': 'NSECM',
            'ExchangeInstrumentID': 2885,
            'TradingSymbol': 'RELIANCE',
            'OrderSide': 'BUY',
            'ProductType': 'CNC',
            'OrderType': 'Limit',
            'TimeInForce': 'DAY',
            'OrderQuantity': 10,
            'CumulativeQuantity': 4,
            'LeavesQuantity': 6,
            'OrderPrice': 2950.5,
            'OrderStopPrice': 0,
            'OrderAverageTradedPrice': '2950.40',
            'OrderGeneratedDateTime': '25-09-2026 10:15:29',
            'ExchangeTransactTime': '25-09-2026 10:15:29',
            'OrderUniqueIdentifier': 'ubi',
        }

    def xts_position(self, day_or_net):
        """A position as XTS pushes it in a `position` event.

        Args:
            day_or_net (str | None): `NET`, `DAY`, or None for an event without the field.

        Returns:
            dict: The position.
        """
        position = {
            'ExchangeSegment': 'NSECM',
            'ExchangeInstrumentID': '2885',
            'TradingSymbol': 'RELIANCE',
            'ProductType': 'CNC',
            'NetQuantity': '4',
            'OpenBuyQuantity': '4',
            'OpenSellQuantity': '0',
            'BuyAveragePrice': '2950.40',
            'SellAveragePrice': '0',
            'RealizedMTM': '0',
            'UnrealizedMTM': '0.4',
            'MTM': '0.4',
        }
        if day_or_net is not None:
            position['DayOrNet'] = day_or_net
        return position
