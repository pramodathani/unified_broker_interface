"""The Stoxkart quote stream and order socket, driven through scripted synchronous connections."""

import json
import struct

from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/stoxkart/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/stoxkart/orders/websocket_order_details'
ORDERS_KEY = 'stoxkart:orders:orders'

TEXT = 0x1
BINARY = 0x2
CLOSE = 0x8

NSE = 1
NFO = 2
MCX = 5


class StubStoxkartAPI(harness.StubBrokerAPI):
    """A stand-in for `StoxkartAPI`.

    Attributes:
        SETTINGS (dict): The client code and api key the order socket authenticates with.
    """

    SETTINGS = {
        'ucc_code': 'SK0001',
        'api_key': 'sk-api-key',
    }


class ContextProviders:
    """Stand-ins for the `get_cache` and `get_logger` the Stoxkart scripts import when they load.

    Attributes:
        context (harness.ScenarioContext): The scenario being run.
    """

    def __init__(self, context):
        """Keeps the scenario.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            None: This method returns nothing.
        """
        self.context = context

    def get_cache(self):
        """The scenario's stand-in Redis client.

        Returns:
            harness.RecordingRedis: The client.
        """
        return self.context.redis

    def get_logger(self, name=None):
        """The scenario's recording logger.

        Args:
            name (str | None): The logger name the script asked for.

        Returns:
            logging.Logger: The logger.
        """
        return self.context.logger


class BroadcastPackets:
    """Builds Stoxkart broadcast packets, little endian, the way `wss://broadcasting-v2.stoxkart.com/` sends them."""

    def packet(self, segment, scrip, code, body):
        """One packet: its 11-byte header and its body.

        Args:
            segment (int): The broadcast segment.
            scrip (int): The scrip id.
            code (int): The packet code.
            body (bytes): The packet after its header.

        Returns:
            bytes: The packet.
        """
        return struct.pack('<BIIBB', segment, scrip, 0, 11 + len(body), code) + body

    def trade(self, segment, scrip, last_price, last_trade, last_update):
        """A trade packet (code 1).

        Args:
            segment (int): The broadcast segment.
            scrip (int): The scrip id.
            last_price (float): The last price.
            last_trade (int): The last trade time, seconds from 1980 in UTC.
            last_update (int): The last update time, India wall clock seconds from 1980.

        Returns:
            bytes: The packet.
        """
        return self.packet(segment, scrip, 1, struct.pack('<fHIfiii', last_price, 25, 1200000, last_price - 0.5, 1234, last_trade, last_update))

    def depth(self, segment, scrip, price):
        """A depth packet (code 2) with five levels a side.

        Args:
            segment (int): The broadcast segment.
            scrip (int): The scrip id.
            price (float): The price the book centres on.

        Returns:
            bytes: The packet.
        """
        body = b''
        for level in range(5):
            body = body + struct.pack('<IIHHff', 100 + level, 200 + level, 1 + level, 2 + level, price - 0.05 * (level + 1), price + 0.05 * (level + 1))
        return self.packet(segment, scrip, 2, body)

    def ohlc(self, segment, scrip):
        """An OHLC packet (code 3).

        Args:
            segment (int): The broadcast segment.
            scrip (int): The scrip id.

        Returns:
            bytes: The packet.
        """
        return self.packet(segment, scrip, 3, struct.pack('<ffff', 2935.0, 2900.0, 2960.0, 2925.0))

    def top_of_book(self, segment, scrip):
        """A top of book packet (code 6).

        Args:
            segment (int): The broadcast segment.
            scrip (int): The scrip id.

        Returns:
            bytes: The packet.
        """
        return self.packet(segment, scrip, 6, struct.pack('<II', 6100, 5400))

    def previous_close(self, segment, scrip, close):
        """A previous close packet (code 32).

        Args:
            segment (int): The broadcast segment.
            scrip (int): The scrip id.
            close (float): The previous close.

        Returns:
            bytes: The packet.
        """
        return self.packet(segment, scrip, 32, struct.pack('<f', close))


class StoxkartFeedCases:
    """Every Stoxkart scenario, and how each stream is built the way its script builds it.

    Attributes:
        loader (harness.ScriptLoader): Loads the two scripts.
        packets (BroadcastPackets): Builds broadcast packets.
    """

    def __init__(self, loader):
        """Keeps the script loader.

        Args:
            loader (harness.ScriptLoader): Loads the two scripts.

        Returns:
            None: This method returns nothing.
        """
        self.loader = loader
        self.packets = BroadcastPackets()

    def stub_modules(self, context):
        """The modules replaced while a Stoxkart scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        return {
            'requests': context.requests_module,
        }

    def attribute_patches(self, context):
        """The names the two scripts bind when they load, replaced with the scenario's stand-ins.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            list: Tuples of an object, an attribute name and its value.
        """
        providers = ContextProviders(context)
        quotes = self.loader.load(QUOTES_SCRIPT)
        orders = self.loader.load(ORDERS_SCRIPT)
        return [
            (quotes, 'websocket', context.websocket_module),
            (quotes, 'get_cache', providers.get_cache),
            (quotes, 'get_logger', providers.get_logger),
            (orders, 'websocket', context.websocket_module),
            (orders, 'requests', context.requests_module),
            (orders, 'StoxkartAPI', StubStoxkartAPI),
            (orders, 'get_cache', providers.get_cache),
            (orders, 'get_logger', providers.get_logger),
        ]

    def datetime_holders(self):
        """The modules whose `datetime` name is frozen while a scenario runs.

        Returns:
            list: The modules.
        """
        return [
            self.loader.load(ORDERS_SCRIPT),
        ]

    def build_quote_stream(self, context, instruments, names):
        """Builds a quote stream the way `bin/stoxkart/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            instruments (list): The `EXCHANGE:TOKEN` instruments.
            names (dict): Instruments to names.

        Returns:
            object: The stream, with an instant stop event.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        stream = script.StoxkartQuoteStream(instruments, names)
        context.use_instant_stop_event(stream)
        return stream

    def build_order_socket(self, context):
        """Builds an order socket the way `bin/stoxkart/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with an instant stop event.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        stoxkart = script.StoxkartAPI()
        socket = script.StoxkartOrderSocket(stoxkart)
        context.use_instant_stop_event(socket)
        return socket

    def scenarios(self):
        """Every Stoxkart scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        return [
            (
                'stoxkart.quotes.every_packet_shape',
                [
                    self.every_packet_connection(),
                    [
                        ('receive', CLOSE, b''),
                    ],
                    [
                        ('raise', harness.FakeWebsocketError('Handshake status 502 Bad Gateway', status_code=502)),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'stoxkart.orders.updates',
                [
                    self.every_order_message_connection(),
                ],
                set(),
                OrdersRunner(self, [self.request_id_answer(1), self.request_id_answer(2)]),
            ),
            (
                'stoxkart.orders.evicted_by_another_session',
                [
                    [
                        ('receive', CLOSE, b'\x03\xe8' + b'Closed: new incoming connection'),
                    ],
                ],
                set(),
                OrdersRunner(self, [self.request_id_answer(1), self.request_id_answer(2)]),
            ),
            (
                'stoxkart.orders.session_refused_logs_in_again',
                [
                    [
                        ('receive', TEXT, b'{"type": "heartbeat"}'),
                    ],
                ],
                set(),
                OrdersRunner(self, [(401, {'code': 'AuthorizationError', 'message': 'Invalid access token'}), self.request_id_answer(2)]),
            ),
            (
                'stoxkart.orders.login_again_fails',
                [],
                {
                    2,
                },
                OrdersRunner(self, [(200, {'code': 'AuthorizationError', 'message': 'Token expired'})]),
            ),
            (
                'stoxkart.orders.authentication_without_a_request_id',
                [
                    [
                        ('timeout',),
                    ],
                ],
                set(),
                OrdersRunner(self, [(200, {'message': 'ok', 'data': {}}), (500, 'Internal Server Error'), self.request_id_answer(3), self.request_id_answer(4)]),
            ),
            (
                'stoxkart.orders.connection_fails',
                [
                    [
                        ('raise', ConnectionRefusedError(111, 'Connection refused')),
                    ],
                ],
                set(),
                OrdersRunner(self, [self.request_id_answer(1), self.request_id_answer(2)]),
            ),
            (
                'stoxkart.orders.first_login_fails',
                [],
                {
                    1,
                },
                OrdersRunner(self, []),
            ),
        ]

    def every_packet_connection(self):
        """One connection carrying every packet shape and frame the quote decoder handles.

        Returns:
            list: The scripted receives.
        """
        full = (
            self.packets.trade(NSE, 2885, 2950.5, 1474796129, 1474815929)
            + self.packets.ohlc(NSE, 2885)
            + self.packets.top_of_book(NSE, 2885)
            + self.packets.previous_close(NSE, 2885, 2930.0)
            + self.packets.depth(NSE, 2885, 2950.5)
        )
        partial = (
            self.packets.trade(MCX, 426016, 0.0, 0, 0)
            + self.packets.packet(MCX, 426016, 33, b'\x00' * 8)
            + self.packets.packet(9, 1, 1, b'\x00' * 26)
            + self.packets.packet(NFO, 35001, 1, b'\x00' * 4)
        )
        return [
            ('receive', BINARY, full),
            ('receive', BINARY, full),
            ('receive', BINARY, partial),
            ('receive', TEXT, b'pong'),
            ('timeout',),
            ('receive', BINARY, struct.pack('<BIIBB', NSE, 2885, 0, 5, 1)),
            ('receive', BINARY, self.packets.trade(NSE, 2885, 2951.0, 1474796130, 1474815930)),
            ('receive', TEXT, b'reconnect'),
        ]

    def every_order_message_connection(self):
        """One connection carrying every kind of message the order socket handles.

        Returns:
            list: The scripted receives.
        """
        first = self.stoxkart_order('SK2609250001', 'COMPLETE', 'NORMAL')
        second = self.stoxkart_order('SK2609250002', 'AMO REQ RECEIVED', 'NORMAL')
        third = self.stoxkart_order('SK2609250003', 'OPEN', '')
        fourth = self.stoxkart_order('SK2609250004', 'OPEN', 'NORMAL')
        return [
            ('receive', TEXT, json.dumps(first).encode('utf-8')),
            ('receive', TEXT, json.dumps([second, third, fourth, 'not a dictionary', {'type': 'heartbeat', 'status': 'ok'}]).encode('utf-8')),
            ('receive', TEXT, b'not json'),
            ('receive', BINARY, b'\x00\x01'),
            ('timeout',),
            ('receive', CLOSE, b'\x03\xe8' + b'server going away'),
        ]

    def request_id_answer(self, number):
        """A successful authentication answer carrying a RequestId.

        Args:
            number (int): Which answer this is, to tell the RequestIds apart.

        Returns:
            tuple: The HTTP status and body.
        """
        return (
            200,
            {
                'message': 'Authentication successful, server assigned',
                'data': {
                    'RequestId': f'request-{number}',
                },
            },
        )

    def seed_stored_varieties(self, context):
        """Stores entries for three of the orders, so the variety the order book gave is kept.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            None: This method returns nothing.
        """
        context.redis.hashes[ORDERS_KEY] = {
            'SK2609250001': json.dumps({'source': 'websocket', 'variety': 'amo'}),
            'SK2609250003': json.dumps({'source': 'rest', 'data': {'variety': 'bo'}}),
            'SK2609250004': 'not json',
        }

    def run_quotes(self, context):
        """Builds a quote stream for three instruments, two named, and runs it.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: What the stream returned.
        """
        instruments = [
            'MCX:426016',
            'NFO:35001',
            'NSE:2885',
        ]
        names = {
            'MCX:426016': 'MCX:CRUDEOIL21OCT26FUT',
            'NFO:35001': '',
            'NSE:2885': 'NSE:RELIANCE',
        }
        stream = self.build_quote_stream(context, instruments, names)
        return {
            'returned': stream.run(),
        }

    def stoxkart_order(self, order_id, status, variety):
        """An order update as Stoxkart's order socket sends it.

        Args:
            order_id (str): The order id.
            status (str): Stoxkart's status.
            variety (str): Stoxkart's variety.

        Returns:
            dict: The update.
        """
        return {
            'client_id': 'SK0001',
            'user_id': 'SK0001',
            'order_id': order_id,
            'exch_order_id': '1100000012345678',
            'order_timestamp': '',
            'order_date_time': '25-09-2026 10:15:29',
            'status': status,
            'reason': '',
            'exchange': 'NSE',
            'symbol': 'RELIANCE',
            'symbol_description': 'RELIANCE INDUSTRIES LTD',
            'token': '2885',
            'action': 'BUY',
            'product_type': 'CNC',
            'order_type': 'LIMIT',
            'validity': 'DAY',
            'variety': variety,
            'quantity': 10,
            'traded_quantity': 4,
            'pending_quantity': 6,
            'price': 2950.5,
            'trigger_price': 0,
            'trade_average_price': 2950.4,
            'tag': 'ubi',
        }


class OrdersRunner:
    """Runs a Stoxkart order socket with scripted authentication answers.

    Attributes:
        cases (StoxkartFeedCases): The cases, which build the socket.
        answers (list): The authentication answers, each a tuple of status and body.
    """

    def __init__(self, cases, answers):
        """Keeps the cases and the answers.

        Args:
            cases (StoxkartFeedCases): The cases, which build the socket.
            answers (list): The authentication answers.

        Returns:
            None: This method returns nothing.
        """
        self.cases = cases
        self.answers = answers

    def __call__(self, context):
        """Builds the order socket and runs it until the scripted connections run out.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: What the socket's run returned, or the error that stopped it being built.
        """
        context.requests_module.answers = list(self.answers)
        self.cases.seed_stored_varieties(context)
        try:
            socket = self.cases.build_order_socket(context)
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        return {
            'returned': socket.run(),
        }
