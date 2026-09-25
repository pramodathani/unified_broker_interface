"""The Groww quotes and order updates sockets, driven through scripted NATS connections."""

import types

from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/groww/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/groww/orders/websocket_order_details'
SOCKET_TOKEN_URL = 'https://api.groww.in/v1/api/apex/v1/socket/token/create/'

INFO = b'INFO {"server_id":"NATS1","nonce":"server-nonce","headers":true,"max_payload":1048576}\r\n'
FIXED_PRIVATE_KEY = bytes(range(32))


class StubGrowwAPI(harness.StubBrokerAPI):
    """A stand-in for `GrowwAPI`; the sockets read only its current login."""


class FixedKeyFactory:
    """Makes the same ed25519 key every time, standing in for `Ed25519PrivateKey.generate` so signatures are the same on every run."""

    @staticmethod
    def generate():
        """Makes the fixed key.

        Returns:
            cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey: A real key built from fixed bytes.
        """
        from cryptography.hazmat.primitives.asymmetric import ed25519

        return ed25519.Ed25519PrivateKey.from_private_bytes(FIXED_PRIVATE_KEY)


class GrowwFeedCases:
    """Every Groww scenario, and how each socket is built the way its script builds it.

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
        """The modules replaced while a Groww scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        api_module = types.ModuleType('stock_brokers.api.groww')
        api_module.GrowwAPI = StubGrowwAPI
        return {
            'stock_brokers.api.groww': api_module,
            'requests': context.requests_module,
        }

    def attribute_patches(self):
        """Makes every generated ed25519 key the same fixed key while a scenario runs.

        Returns:
            list: Tuples of an object, an attribute name and its value.
        """
        from cryptography.hazmat.primitives.asymmetric import ed25519

        return [
            (
                ed25519.Ed25519PrivateKey,
                'generate',
                FixedKeyFactory.generate,
            ),
        ]

    def datetime_holders(self):
        """The modules whose `datetime` name is frozen while a scenario runs.

        Returns:
            list: The modules.
        """
        return [
            self.loader.load(ORDERS_SCRIPT),
        ]

    def quote_message_class(self):
        """The `StocksSocketResponseProtoDto` class the quote payloads are built with.

        Returns:
            type: The protobuf message class.
        """
        return self.loader.load(QUOTES_SCRIPT).stocks_response_class()

    def order_message_classes(self):
        """The `OrderDetailsBroadCastDto` and `PositionDetailProto` classes the order payloads are built with.

        Returns:
            tuple: The two protobuf message classes.
        """
        return self.loader.load(ORDERS_SCRIPT).message_classes()

    def build_quotes_socket(self, context, tokens, names):
        """Builds a quotes socket the way `bin/groww/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The `EXCHANGE|SEGMENT|EXCHANGE_TOKEN` tokens to subscribe to.
            names (dict): Tokens to instrument names.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = script.GrowwSession(context.logger)
        socket = script.QuotesSocket('socket_0', tokens, names, session, context.redis, context.logger)
        context.use_instant_waits(socket)
        return socket

    def build_order_socket(self, context):
        """Builds an order updates socket the way `bin/groww/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        socket = script.OrderUpdatesSocket(context.redis, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every Groww scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        authorization_error = b"-ERR 'Authorization Violation'\r\n"
        return [
            (
                'groww.quotes.every_frame_shape',
                [
                    self.every_quote_frame_connection(),
                ],
                set(),
                self.run_quotes_with_answers(2),
            ),
            (
                'groww.quotes.socket_token_refused_logs_in_again',
                [
                    [
                        ('open',),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes_refused_then_accepted,
            ),
            (
                'groww.quotes.nats_authorization_error_logs_in_again',
                [
                    [
                        ('open',),
                        ('message', INFO),
                        ('message', authorization_error),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_with_answers(3),
            ),
            (
                'groww.quotes.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', INFO),
                        ('message', authorization_error.decode('utf-8')),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_with_answers(3),
            ),
            (
                'groww.quotes.refused_again_logs_in_again',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_refused_twice_then_accepted,
            ),
            (
                'groww.quotes.failed_connects_give_up',
                [],
                set(),
                self.run_quotes_failing_token_requests,
            ),
            (
                'groww.quotes.socket_token_without_a_token',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_without_a_token_first,
            ),
            (
                'groww.quotes.login_again_fails',
                [],
                {
                    2,
                },
                self.run_quotes_refused_then_accepted,
            ),
            (
                'groww.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes_with_answers(0),
            ),
            (
                'groww.orders.updates',
                [
                    self.every_order_frame_connection(),
                ],
                set(),
                self.run_orders_with_answers(2),
            ),
            (
                'groww.orders.socket_token_refused_logs_in_again',
                [
                    [
                        ('open',),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders_refused_then_accepted,
            ),
            (
                'groww.orders.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', INFO),
                        ('message', authorization_error),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders_with_answers(3),
            ),
            (
                'groww.orders.socket_token_without_a_subscription_id',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders_without_a_subscription_id_first,
            ),
            (
                'groww.orders.refused_again_gives_up',
                [],
                set(),
                self.run_orders_refused_twice,
            ),
            (
                'groww.orders.failed_connects_give_up',
                [],
                set(),
                self.run_orders_failing_token_requests,
            ),
            (
                'groww.orders.login_again_fails',
                [],
                {
                    2,
                },
                self.run_orders_refused_twice,
            ),
            (
                'groww.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders_with_answers(0),
            ),
        ]

    def token_answer(self, number):
        """A socket token answer carrying a JWT and a subscription id.

        Args:
            number (int): Which answer this is, to tell the JWTs apart.

        Returns:
            tuple: The HTTP status and body.
        """
        return (
            200,
            {
                'payload': {
                    'token': f'socket-jwt-{number}',
                    'subscriptionId': f'subscription-{number}',
                },
            },
        )

    def run_quotes_with_answers(self, count):
        """A runner for a quotes socket whose socket token requests all succeed.

        Args:
            count (int): How many token requests to answer.

        Returns:
            callable: The runner.
        """
        answers = []
        for number in range(1, count + 1):
            answers.append(self.token_answer(number))
        return QuotesRunner(self, answers)

    def run_orders_with_answers(self, count):
        """A runner for an order socket whose socket token requests all succeed.

        Args:
            count (int): How many token requests to answer.

        Returns:
            callable: The runner.
        """
        answers = []
        for number in range(1, count + 1):
            answers.append(self.token_answer(number))
        return OrdersRunner(self, answers)

    def run_quotes_refused_then_accepted(self, context):
        """Runs a quotes socket whose first socket token request is refused.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = [
            (401, '{"message":"Unauthorized"}'),
            self.token_answer(2),
            self.token_answer(3),
        ]
        return QuotesRunner(self, answers)(context)

    def run_quotes_refused_twice_then_accepted(self, context):
        """Runs a quotes socket refused twice in a row, which Groww's quotes loop answers by logging in again each time.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = [
            (403, 'Forbidden'),
            (401, 'Unauthorized'),
            self.token_answer(3),
            self.token_answer(4),
        ]
        return QuotesRunner(self, answers)(context)

    def run_quotes_failing_token_requests(self, context):
        """Runs a quotes socket whose socket token requests keep failing with a server error.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = []
        for _ in range(12):
            answers.append((500, 'Internal Server Error'))
        return QuotesRunner(self, answers)(context)

    def run_quotes_without_a_token_first(self, context):
        """Runs a quotes socket whose first socket token answer carries no token.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = [
            (200, {'payload': {'subscriptionId': 'subscription-1'}}),
            self.token_answer(2),
            self.token_answer(3),
        ]
        return QuotesRunner(self, answers)(context)

    def run_orders_refused_then_accepted(self, context):
        """Runs an order socket whose first socket token request is refused.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = [
            (401, '{"message":"Unauthorized"}'),
            self.token_answer(2),
            self.token_answer(3),
        ]
        return OrdersRunner(self, answers)(context)

    def run_orders_without_a_subscription_id_first(self, context):
        """Runs an order socket whose first socket token answer carries no subscription id.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = [
            (200, {'token': 'socket-jwt-1'}),
            self.token_answer(2),
            self.token_answer(3),
        ]
        return OrdersRunner(self, answers)(context)

    def run_orders_refused_twice(self, context):
        """Runs an order socket refused before and after logging in again.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = [
            (401, 'Unauthorized'),
            (401, 'Unauthorized'),
        ]
        return OrdersRunner(self, answers)(context)

    def run_orders_failing_token_requests(self, context):
        """Runs an order socket whose socket token requests keep failing with a server error.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        answers = []
        for _ in range(12):
            answers.append((500, 'Internal Server Error'))
        return OrdersRunner(self, answers)(context)

    def log_in_elsewhere(self):
        """Replaces the token as another process logging in would.

        Returns:
            None: This method returns nothing.
        """
        harness.StubBrokerAPI.logins.replace_elsewhere('token-from-another-process')

    def nats_message(self, subject, payload):
        """One NATS `MSG` with its payload.

        Args:
            subject (str): The subject.
            payload (bytes): The payload.

        Returns:
            bytes: The framed message.
        """
        return f'MSG {subject} 1 {len(payload)}\r\n'.encode('utf-8') + payload + b'\r\n'

    def every_quote_frame_connection(self):
        """One connection carrying every kind of NATS frame and protobuf payload the quotes decoder handles.

        Returns:
            list: The scripted steps.
        """
        response_class = self.quote_message_class()
        price = response_class()
        price.symbol = 'RELIANCE'
        price.stockLivePrice.tsInMillis = 1790316329123
        price.stockLivePrice.ltp = 295050
        price.stockLivePrice.open = 293500
        price.stockLivePrice.high = 296000
        price.stockLivePrice.low = 292500
        price.stockLivePrice.close = 293000
        price.stockLivePrice.volume = 1200000.4
        price.stockLivePrice.bidQty = 5400
        price.stockLivePrice.offerQty = 6100
        price.stockLivePrice.avgPrice = 294810
        depth = response_class()
        depth.stocksMarketDepth.tsInMillis = 1790316330123
        depth.stocksMarketDepth.buyBook[2].price = 295000
        depth.stocksMarketDepth.buyBook[2].qty = 300
        depth.stocksMarketDepth.buyBook[1].price = 295040
        depth.stocksMarketDepth.buyBook[1].qty = 75.6
        depth.stocksMarketDepth.sellBook[1].price = 295060
        depth.stocksMarketDepth.sellBook[1].qty = 150
        futures = response_class()
        futures.symbol = 'NIFTY26OCTFUT'
        futures.stockLivePrice.ltp = 2515050
        futures.stockLivePrice.openInterest = 1234500
        index = response_class()
        index.stocksLiveIndices.value = 2512345
        index.stocksLiveIndices.tsInMillis = 1790316329000
        nothing = response_class()
        nothing.symbol = 'SBIN'
        nothing.stockLivePrice.open = 80000
        price_message = self.nats_message('/ld/eq/nse/price_detailed.2885', price.SerializeToString())
        return [
            ('open',),
            ('message', INFO),
            ('message', 'PING\r\n'),
            ('message', price_message[:20]),
            ('message', price_message[20:] + self.nats_message('/ld/eq/nse/book.2885', depth.SerializeToString())),
            ('message', self.nats_message('/ld/fo/nse/price_detailed.35001', futures.SerializeToString())),
            ('message', self.nats_message('/ld/eq/nse/price_detailed.NIFTY', index.SerializeToString())),
            ('message', self.nats_message('/ld/eq/bse/price_detailed.500325', nothing.SerializeToString())),
            ('message', self.nats_message('/ld/eq/nse/price_detailed.99999', price.SerializeToString())),
            ('message', self.nats_message('/ld/eq/nse/book.2885', b'\xff\xff\xff not protobuf')),
            ('message', b'MSG broken\r\n+OK\r\n'),
            ('message', b"-ERR 'Slow Consumer'\r\n"),
            ('close', 1000, 'normal closure'),
        ]

    def every_order_frame_connection(self):
        """One connection carrying every kind of NATS frame and protobuf payload the order decoder handles.

        Returns:
            list: The scripted steps.
        """
        from google.protobuf import json_format

        order_class, position_class = self.order_message_classes()
        equity = json_format.ParseDict(
            {
                'orderDetailUpdateDto': {
                    'growwOrderId': 'GMK2609250001',
                    'exchangeOrderId': '1100000012345678',
                    'orderStatus': 'EXECUTED',
                    'duration': 'DAY',
                    'exchange': 'NSE',
                    'segment': 'CASH',
                    'product': 'CNC',
                    'orderType': 'L',
                    'buySell': 'B',
                    'qty': 10,
                    'filledQty': 10,
                    'price': 295050,
                    'avgFillPrice': 295040,
                    'contractId': 'RELIANCE',
                    'remark': 'ubi',
                },
                'stageAndTimeStamp': [
                    {
                        'stageName': 'NEW',
                        'timeStampFromMidNight': 36920,
                    },
                    {
                        'stageName': 'EXECUTED',
                        'timeStampFromMidNight': 36929,
                    },
                ],
            },
            order_class(),
        )
        derivatives = json_format.ParseDict(
            {
                'orderDetailUpdateDto': {
                    'growwOrderId': 'GMK2609250002',
                    'orderStatus': 'ACKED',
                    'segment': 'FNO',
                    'product': 'NRML',
                    'buySell': 'S',
                    'qty': 75,
                    'contractId': 'NIFTY26OCT25000CE',
                },
            },
            order_class(),
        )
        without_id = json_format.ParseDict(
            {
                'orderDetailUpdateDto': {
                    'qty': 1,
                },
            },
            order_class(),
        )
        without_dto = order_class()
        position = json_format.ParseDict(
            {
                'symbolData': {
                    'contractId': 'NIFTY26OCT25000CE',
                    'displayName': 'NIFTY 25000 CE',
                    'stocksProduct': 'NRML',
                    'exchange': 'NSE',
                },
                'positionInfo': {
                    'NSE': {
                        'creditQty': 75,
                        'creditPrice': 12050,
                    },
                },
            },
            position_class(),
        )
        without_symbol = json_format.ParseDict(
            {
                'positionInfo': {
                    'NSE': {
                        'debitQty': 75,
                    },
                },
            },
            position_class(),
        )
        equity_subject = 'stocks/order/updates.apex.subscription-1'
        derivatives_subject = 'stocks_fo/order/updates.apex.subscription-1'
        position_subject = 'stocks_fo/position/updates.apex.subscription-1'
        return [
            ('open',),
            ('message', INFO),
            ('message', 'PING\r\n'),
            ('message', self.nats_message(equity_subject, equity.SerializeToString())),
            ('message', self.nats_message(derivatives_subject, derivatives.SerializeToString()) + self.nats_message(position_subject, position.SerializeToString())),
            ('message', self.nats_message(equity_subject, without_id.SerializeToString()) + self.nats_message(equity_subject, without_dto.SerializeToString())),
            ('message', self.nats_message(position_subject, without_symbol.SerializeToString())),
            ('message', self.nats_message('stocks/order/updates.apex.somebody-else', equity.SerializeToString())),
            ('message', self.nats_message(equity_subject, b'\xff\xff\xff not protobuf')),
            ('message', b"-ERR 'Slow Consumer'\r\n"),
            ('close', 1000, 'normal closure'),
        ]


class QuotesRunner:
    """Runs a Groww quotes socket with scripted socket token answers.

    Attributes:
        cases (GrowwFeedCases): The cases, which build the socket.
        answers (list): The socket token answers, each a tuple of status and body.
    """

    def __init__(self, cases, answers):
        """Keeps the cases and the answers.

        Args:
            cases (GrowwFeedCases): The cases, which build the socket.
            answers (list): The socket token answers.

        Returns:
            None: This method returns nothing.
        """
        self.cases = cases
        self.answers = answers

    def __call__(self, context):
        """Builds a quotes socket for four instruments, one named, and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built, and the names the socket learned.
        """
        context.requests_module.answers = list(self.answers)
        tokens = [
            'BSE|CASH|500325',
            'NSE|CASH|2885',
            'NSE|CASH|NIFTY',
            'NSE|FNO|35001',
        ]
        names = {
            'NSE|CASH|2885': 'NSE:RELIANCE',
        }
        try:
            socket = self.cases.build_quotes_socket(context, tokens, names)
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
            'names': names,
        }


class OrdersRunner:
    """Runs a Groww order updates socket with scripted socket token answers.

    Attributes:
        cases (GrowwFeedCases): The cases, which build the socket.
        answers (list): The socket token answers, each a tuple of status and body.
    """

    def __init__(self, cases, answers):
        """Keeps the cases and the answers.

        Args:
            cases (GrowwFeedCases): The cases, which build the socket.
            answers (list): The socket token answers.

        Returns:
            None: This method returns nothing.
        """
        self.cases = cases
        self.answers = answers

    def __call__(self, context):
        """Builds an order updates socket and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        context.requests_module.answers = list(self.answers)
        try:
            socket = self.cases.build_order_socket(context)
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }
