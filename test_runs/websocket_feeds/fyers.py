"""The Fyers quotes and order updates sockets, driven through scripted HSM and trade stream connections."""

import base64
import json
import struct
import types

from stock_brokers.websockets import fyers as fyers_websockets
from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/fyers/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/fyers/orders/websocket_order_details'

AUTH_RESPONSE = 1
SUBSCRIBE = 4
DATAFEED_RESPONSE = 6
SNAPSHOT = 83
UPDATE = 85
LITE = 76
NO_VALUE = -2147483648


class StubFyersAPI(harness.StubBrokerAPI):
    """A stand-in for `FyersAPI`, whose tokens are JWTs carrying `exp` and `hsm_key` and whose `get` answers the profile check.

    Attributes:
        SETTINGS (dict): The app id the sockets send with the token.
        refused_profiles (set): The login numbers whose profile check is refused.
    """

    SETTINGS = {
        'app_id': 'APPID-100',
    }
    refused_profiles = set()

    def _current_login(self):
        """The login in force now, its token a JWT whose claims depend on the ledger token's name.

        A ledger token starting with `expired` gets an expiry in the past, and one starting with `nohsm` carries no `hsm_key`.

        Returns:
            dict | None: The access token in force, or None before any login.
        """
        token = harness.StubBrokerAPI.logins.current_token
        if token is None:
            return None
        claims = {
            'exp': int(harness.FROZEN_MOMENT.timestamp()) + 86400,
            'hsm_key': f'hsm-{token}',
        }
        if token.startswith('expired'):
            claims['exp'] = int(harness.FROZEN_MOMENT.timestamp()) - 1
        if token.startswith('nohsm'):
            del claims['hsm_key']
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode('utf-8')).decode('ascii').rstrip('=')
        return {
            'access_token': f'header.{payload}.signature',
        }

    def get(self, url, timeout=None):
        """Answers the profile check for the login in force, refusing it when the scenario says so.

        Args:
            url (str): The endpoint.
            timeout (float | None): The request timeout.

        Returns:
            dict: The response, as `BrokerAPI.get` returns it.
        """
        ledger = harness.StubBrokerAPI.logins
        ledger.event_log.add('get', url, timeout)
        if ledger.login_count in StubFyersAPI.refused_profiles:
            return {
                'data': {
                    's': 'error',
                    'code': -16,
                    'message': 'Could not authenticate the user',
                },
            }
        return {
            'data': {
                's': 'ok',
                'code': 200,
                'data': {
                    'fy_id': 'XY01234',
                },
            },
        }


class HsmFrames:
    """Builds Fyers HSM binary frames, the way `wss://socket.fyers.in/hsm/v1-5/prod` sends them."""

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
        return (
            struct.pack('!HBBB', 0, AUTH_RESPONSE, 2, 1)
            + struct.pack('!H', len(status))
            + status
            + bytes([2])
            + struct.pack('!H', 4)
            + struct.pack('>I', ack_count)
        )

    def subscribe_response(self, accepted):
        """A subscription response.

        Args:
            accepted (bool): Whether the subscription was accepted.

        Returns:
            bytes: The frame.
        """
        status = b'K'
        if not accepted:
            status = b'N'
        return struct.pack('!HBBBH', 0, SUBSCRIBE, 1, 1, 1) + status

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
                value = NO_VALUE
            packed = packed + struct.pack('>i', value)
        return packed

    def snapshot(self, topic_id, topic_name, values, multiplier, precision):
        """A snapshot packet naming a topic and carrying every field, then the price scale and three strings.

        Args:
            topic_id (int): The topic id later updates refer to.
            topic_name (str): The topic name.
            values (list): The positional values.
            multiplier (int): The price multiplier.
            precision (int): The price precision.

        Returns:
            bytes: The packet.
        """
        name = topic_name.encode('ascii')
        return (
            bytes([SNAPSHOT])
            + struct.pack('H', topic_id)
            + bytes([len(name)])
            + name
            + bytes([len(values)])
            + self.values(values)
            + b'\x00\x00'
            + struct.pack('>H', multiplier)
            + bytes([precision])
            + bytes([3]) + b'NSE'
            + bytes([4]) + b'3045'
            + bytes([4]) + b'SBIN'
        )

    def update(self, topic_id, values, packet_type=UPDATE):
        """An update packet carrying positional values for a topic id.

        Args:
            topic_id (int): The topic id.
            values (list): The positional values.
            packet_type (int): 85 for an update, 76 for a lite update.

        Returns:
            bytes: The packet.
        """
        return bytes([packet_type]) + struct.pack('H', topic_id) + bytes([len(values)]) + self.values(values)

    def datafeed(self, message_number, packets):
        """A data feed response holding packets.

        Args:
            message_number (int): The message number an acknowledgement refers to.
            packets (list): The packets.

        Returns:
            bytes: The frame.
        """
        frame = struct.pack('!H', 0) + bytes([DATAFEED_RESPONSE]) + struct.pack('>I', message_number) + struct.pack('!H', len(packets))
        for packet in packets:
            frame = frame + packet
        return frame


class FyersFeedCases:
    """Every Fyers scenario, and how each socket is built the way its script builds it.

    Attributes:
        loader (harness.ScriptLoader): Loads the two scripts.
        frames (HsmFrames): Builds HSM frames.
    """

    def __init__(self, loader):
        """Keeps the script loader.

        Args:
            loader (harness.ScriptLoader): Loads the two scripts.

        Returns:
            None: This method returns nothing.
        """
        self.loader = loader
        self.frames = HsmFrames()

    def stub_modules(self, context):
        """The modules replaced while a Fyers scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        StubFyersAPI.refused_profiles = set()
        api_module = types.ModuleType('stock_brokers.api.fyers')
        api_module.FyersAPI = StubFyersAPI
        return {
            'stock_brokers.api.fyers': api_module,
            'requests': context.requests_module,
        }

    def attribute_patches(self):
        """The attributes replaced while a scenario runs; none for this broker.

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
            fyers_websockets,
        ]

    def build_quotes_socket(self, context, symbols):
        """Builds a quotes socket the way `bin/fyers/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            symbols (list): The Fyers symbols to subscribe to.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = fyers_websockets.FyersSession(context.logger)
        store = script.FyersQuotesStore(context.redis)
        socket = fyers_websockets.FyersQuotesSocket('socket_0', symbols, session, store.write_ticks, context.logger)
        context.use_instant_waits(socket)
        return socket

    def build_order_socket(self, context):
        """Builds an order updates socket the way `bin/fyers/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        store = script.FyersOrderUpdatesStore(context.redis, context.logger)
        session = fyers_websockets.FyersSession(context.logger)
        socket = fyers_websockets.FyersOrderUpdatesSocket(session, store.write_updates, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every Fyers scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        feed_refused = [
            ('open',),
            ('message', self.frames.auth_response(False, 0)),
        ]
        handshake_refused = harness.FakeWebsocketError('Handshake status 403 Forbidden', status_code=403)
        return [
            (
                'fyers.quotes.every_packet_shape',
                [
                    self.every_packet_connection(),
                ],
                set(),
                QuotesRunner(self, [self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.feed_authentication_refused_logs_in_again',
                [
                    feed_refused,
                    [
                        ('open',),
                    ],
                ],
                set(),
                QuotesRunner(self, [self.lookup_answer(), self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.symbol_lookup_refuses_the_session',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                QuotesRunner(self, [(200, {'s': 'error', 'code': -16, 'message': 'Could not authenticate the user'}), self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.cloudflare_block_pauses',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                QuotesRunner(self, [(429, '<html>Error 1015 - You are being rate limited. Cloudflare has banned you temporarily.</html>'), self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.rate_limit_pauses',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                QuotesRunner(self, [(429, {'s': 'error', 'code': 429, 'message': 'Too many requests'}), self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.other_lookup_error_fails_the_connect',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                QuotesRunner(self, [(500, {'s': 'error', 'code': -99, 'message': 'Something went wrong'}), self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.no_symbol_resolves',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                QuotesRunner(self, [(200, {'s': 'ok', 'validSymbol': {}, 'invalidSymbol': ['NSE:SBIN-EQ']}), self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.expired_token_logs_in_again',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                ExpiredTokenQuotesRunner(self, [self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', self.frames.auth_response(False, 0)),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                QuotesRunner(self, [self.lookup_answer(), self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.refused_again_gives_up',
                [
                    feed_refused,
                    feed_refused,
                ],
                set(),
                QuotesRunner(self, [self.lookup_answer(), self.lookup_answer()]),
            ),
            (
                'fyers.quotes.failed_connects_give_up',
                [],
                set(),
                QuotesRunner(self, self.failing_lookups(12)),
            ),
            (
                'fyers.quotes.login_again_fails',
                [
                    feed_refused,
                ],
                {
                    2,
                },
                QuotesRunner(self, [self.lookup_answer()]),
            ),
            (
                'fyers.quotes.first_login_fails',
                [],
                {
                    1,
                },
                QuotesRunner(self, []),
            ),
            (
                'fyers.quotes.first_profile_refused',
                [],
                set(),
                RefusedProfileQuotesRunner(self, []),
            ),
            (
                'fyers.orders.updates',
                [
                    self.every_order_message_connection(),
                ],
                set(),
                self.run_orders,
            ),
            (
                'fyers.orders.session_error_closes_after_writing',
                [
                    [
                        ('open',),
                        ('message', json.dumps([{'s': 'ok', 'orders': self.fyers_order('26092500000009', 2)}, {'s': 'error', 'code': -15, 'message': 'Invalid token'}])),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'fyers.orders.handshake_refused_logs_in_again',
                [
                    [
                        ('error', handshake_refused),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'fyers.orders.expired_token_logs_in_again',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders_with_an_expired_token,
            ),
            (
                'fyers.orders.token_replaced_elsewhere',
                [
                    [
                        ('call', self.log_in_elsewhere),
                        ('error', handshake_refused),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'fyers.orders.refused_again_gives_up',
                [
                    [
                        ('error', handshake_refused),
                    ],
                    [
                        ('error', handshake_refused),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'fyers.orders.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_orders,
            ),
            (
                'fyers.orders.login_again_fails',
                [
                    [
                        ('error', handshake_refused),
                    ],
                ],
                {
                    2,
                },
                self.run_orders,
            ),
            (
                'fyers.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders,
            ),
            (
                'fyers.orders.first_profile_refused',
                [],
                set(),
                self.run_orders_with_the_first_profile_refused,
            ),
        ]

    def lookup_answer(self):
        """A symbol-token answer resolving three of the five symbols to feed topics.

        Returns:
            tuple: The HTTP status and body.
        """
        return (
            200,
            {
                's': 'ok',
                'validSymbol': {
                    'NSE:SBIN-EQ': '10100000003045',
                    'NSE:NIFTY50-INDEX': '101000000026000',
                    'NSE:NIFTYMIDCAP150-INDEX': '101000000026060',
                    'MCX:CRUDEOIL26OCTFUT': '1120000000426016',
                    'NSE:UNKNOWN-EQ': '99990000001234',
                },
                'invalidSymbol': [
                    'NSE:MISSING-EQ',
                ],
            },
        )

    def failing_lookups(self, count):
        """Symbol lookups that fail for a reason other than the session.

        Args:
            count (int): How many fail.

        Returns:
            list: The answers.
        """
        answers = []
        for _ in range(count):
            answers.append((500, {'s': 'error', 'code': -99, 'message': 'Something went wrong'}))
        return answers

    def every_packet_connection(self):
        """One connection carrying every HSM frame and packet shape the quotes decoder handles.

        Returns:
            list: The scripted steps.
        """
        data_values = [
            62050,
            1200000,
            1790316328,
            1790316329,
            500,
            600,
            62040,
            62060,
            25,
            5400,
            6100,
            62010,
            None,
            61500,
            62300,
            70000,
            50000,
            55000,
            68000,
            61800,
            61900,
        ]
        index_values = [
            2512345,
            2495000,
            1790316329,
            2520000,
            2490000,
            2500000,
        ]
        depth_values = [
            62040,
            62030,
            62020,
            62010,
            62000,
            62060,
            62070,
            62080,
            62090,
            62100,
            10,
            20,
            30,
            40,
            50,
            11,
            21,
            31,
            41,
            51,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
        ]
        first_feed = self.frames.datafeed(
            1,
            [
                self.frames.snapshot(1, 'sf|nse_cm|3045', data_values, 1, 2),
                self.frames.snapshot(2, 'if|nse_cm|Nifty 50', index_values, 1, 2),
                self.frames.snapshot(3, 'dp|nse_cm|3045', depth_values, 1, 2),
            ],
        )
        second_feed = self.frames.datafeed(
            2,
            [
                self.frames.update(1, [62075, 1200050]),
                self.frames.update(2, [2512400], LITE),
                self.frames.update(9, [1, 2, 3]),
                bytes([99]),
            ],
        )
        return [
            ('open',),
            ('message', self.frames.auth_response(True, 2)),
            ('message', self.frames.subscribe_response(True)),
            ('message', self.frames.subscribe_response(False)),
            ('message', first_feed),
            ('message', second_feed),
            ('message', self.frames.datafeed(3, [self.frames.snapshot(4, 'sf|mcx_fo|426016', [612300, 1000], 1, 2)])[:20]),
            ('message', b'\x00\x00\x06\x00\x00\x00\x04'),
            ('message', b'\x00\x00\x09unknown'),
            ('message', 'text frame'),
            ('message', b'\x00'),
            ('close', 1000, 'normal closure'),
        ]

    def every_order_message_connection(self):
        """One connection carrying every kind of message the order decoder handles.

        Returns:
            list: The scripted steps.
        """
        without_id = self.fyers_order('', 6)
        without_symbol = self.fyers_position('')
        return [
            ('open',),
            ('message', json.dumps({'s': 'ok', 'code': 1605, 'message': 'Successfully subscribed'})),
            ('message', json.dumps({'s': 'ok', 'orders': self.fyers_order('26092500000001', 2)})),
            ('message', json.dumps({'s': 'ok', 'positions': self.fyers_position('NSE:SBIN-EQ')})),
            ('message', json.dumps([{'s': 'ok', 'orders': self.fyers_order('26092500000002', 6)}, {'s': 'ok', 'orders': without_id}, {'s': 'ok', 'positions': without_symbol}, {'s': 'ok', 'trades': {'id': 'T1'}}, {'s': 'ok', 'something': 'else'}, 'not a dictionary'])),
            ('message', json.dumps({'s': 'error', 'code': 'not a number', 'message': 'Odd error'})),
            ('message', json.dumps({'s': 'error', 'code': -300, 'message': 'Other error'})),
            ('message', 'pong'),
            ('message', ''),
            ('message', 'not json'),
            ('message', json.dumps({'s': 'ok', 'orders': self.fyers_order('26092500000003', 5)}).encode('utf-8')),
            ('message', 12345),
            ('close', 1000, 'normal closure'),
        ]

    def run_orders(self, context):
        """Builds an order updates socket and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        try:
            socket = self.build_order_socket(context)
        except Exception as error:
            return {
                'build_error': f'{type(error).__name__}: {error}',
            }
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }

    def run_orders_with_an_expired_token(self, context):
        """Runs an order socket whose stored token has expired by the time it connects.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        try:
            socket = self.build_order_socket(context)
        except Exception as error:
            return {
                'build_error': f'{type(error).__name__}: {error}',
            }
        context.logins.replace_elsewhere('expired-token')
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }

    def run_orders_with_the_first_profile_refused(self, context):
        """Builds an order socket whose first login's profile check is refused.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: The error that stopped the socket being built.
        """
        StubFyersAPI.refused_profiles = {
            1,
        }
        return self.run_orders(context)

    def log_in_elsewhere(self):
        """Replaces the token as another process logging in would.

        Returns:
            None: This method returns nothing.
        """
        harness.StubBrokerAPI.logins.replace_elsewhere('token-from-another-process')

    def fyers_order(self, order_id, status):
        """An order as Fyers sends it in an `orders` message.

        Args:
            order_id (str): The order id.
            status (int): Fyers' order status code.

        Returns:
            dict: The order.
        """
        return {
            'id': order_id,
            'id_exchange': '1100000012345678',
            'org_ord_status': status,
            'symbol': 'NSE:SBIN-EQ',
            'exchange': 10,
            'segment': 10,
            'fy_token': '10100000003045',
            'tran_side': 1,
            'ord_type': 1,
            'product_type': 'CNC',
            'validity': 'DAY',
            'qty': 10,
            'qty_filled': 4,
            'qty_remaining': 6,
            'price_limit': 620.5,
            'price_stop': 0,
            'price_traded': 620.4,
            'time_oms': '25-Sep-2026 10:15:29',
            'oms_msg': 'CONFIRMED',
            'ordertag': 'ubi',
        }

    def fyers_position(self, symbol):
        """A position as Fyers sends it in a `positions` message.

        Args:
            symbol (str): The Fyers symbol.

        Returns:
            dict: The position.
        """
        return {
            'symbol': symbol,
            'fy_token': '10100000003045',
            'exchange': 10,
            'segment': 10,
            'product_type': 'INTRADAY',
            'buy_qty': 10,
            'sell_qty': 4,
            'net_qty': 6,
            'buy_avg': 620.4,
            'sell_avg': 621.0,
            'net_avg': 620.4,
            'buy_val': 6204.0,
            'sell_val': 2484.0,
            'cf_buy_qty': 0,
            'cf_sell_qty': 0,
            'pl_realized': 2.4,
            'pl_unrealized': 0.6,
            'pl_total': 3.0,
            'qty_multiplier': 1,
        }


class QuotesRunner:
    """Runs a Fyers quotes socket with scripted symbol lookup answers.

    Attributes:
        cases (FyersFeedCases): The cases, which build the socket.
        answers (list): The symbol lookup answers, each a tuple of status and body.
    """

    def __init__(self, cases, answers):
        """Keeps the cases and the answers.

        Args:
            cases (FyersFeedCases): The cases, which build the socket.
            answers (list): The symbol lookup answers.

        Returns:
            None: This method returns nothing.
        """
        self.cases = cases
        self.answers = answers

    def symbols(self):
        """The five symbols every Fyers quotes scenario subscribes to.

        Returns:
            list: The symbols.
        """
        return [
            'MCX:CRUDEOIL26OCTFUT',
            'NSE:MISSING-EQ',
            'NSE:NIFTY50-INDEX',
            'NSE:NIFTYMIDCAP150-INDEX',
            'NSE:SBIN-EQ',
        ]

    def prepare(self, context):
        """Loads the scripted answers before the socket is built.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            None: This method returns nothing.
        """
        context.requests_module.answers = list(self.answers)

    def before_running(self, context):
        """Changes the world after the socket is built and before it runs; nothing by default.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            None: This method returns nothing.
        """

    def __call__(self, context):
        """Builds the quotes socket and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        self.prepare(context)
        try:
            socket = self.cases.build_quotes_socket(context, self.symbols())
        except Exception as error:
            return {
                'build_error': f'{type(error).__name__}: {error}',
            }
        self.before_running(context)
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }


class ExpiredTokenQuotesRunner(QuotesRunner):
    """Runs a Fyers quotes socket whose stored token has expired by the time it connects."""

    def before_running(self, context):
        """Replaces the stored token with an expired one.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            None: This method returns nothing.
        """
        context.logins.replace_elsewhere('expired-token')


class RefusedProfileQuotesRunner(QuotesRunner):
    """Runs a Fyers quotes socket whose first login's profile check is refused."""

    def prepare(self, context):
        """Scripts the first profile check to be refused.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            None: This method returns nothing.
        """
        super().prepare(context)
        StubFyersAPI.refused_profiles = {
            1,
        }
