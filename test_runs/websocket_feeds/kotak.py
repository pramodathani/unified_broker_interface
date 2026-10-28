"""The Kotak quotes and order updates sockets, driven through scripted SFeed and realtime connections."""

import json
import struct
import types

from stock_brokers.websockets import kotak as kotak_websockets
from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/kotak/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/kotak/orders/websocket_order_details'

PACKET_HEADER = struct.Struct('<HHbBBBB')
MARKET_PICTURE = struct.Struct('<IqqqqqIIIIIqIIIIhiIdiIIIIIBI')
DEPTH_ROW = struct.Struct('<qii')
NSE_CM = 1
CDE_FO = 3
MCX_FO = 9
MARKET_PICTURE_CODE = 7208
CLOSING_AUCTION_CODE = 104

class StubKotakAPI(harness.StubBrokerAPI):
    """A stand-in for `KotakAPI`, whose login carries a session id, the account's host and the market feed's address as Kotak's does.

    A ledger token starting with `nosid` has no session id, one starting with `nobaseurl` has no host, and one starting with `feedurl` names its own market feed.
    """

    SETTINGS = {
        'ucc_code': 'UCC01',
    }

    def _current_login(self):
        """The login in force now.

        Returns:
            dict | None: The access token, session id, host and market feed address, or None before any login.
        """
        token = harness.StubBrokerAPI.logins.current_token
        if token is None:
            return None
        login = {
            'access_token': token,
            'sid': f'sid-{token}',
            'base_url': 'https://e21.kotaksecurities.com/',
            'feed_url': None,
        }
        if token.startswith('nosid'):
            login['sid'] = None
        if token.startswith('nobaseurl'):
            login['base_url'] = None
        if token.startswith('feedurl'):
            login['feed_url'] = 'wss://sfeed-e21.kotaksecurities.com/apifeed'
        return login


class KotakFeedMessages:
    """Builds the messages of Kotak's SFeed market feed, JSON control messages and little-endian binary packets, as `wss://sfeed.kotaksecurities.com/apifeed` sends them."""

    def authentication_answer(self, message_code):
        """An answer to the authentication message, carrying the exchanges and their price dividers.

        Args:
            message_code (int): 1119 or 1117.

        Returns:
            str: The message.
        """
        return json.dumps({
            'message_code': message_code,
            'id': 'SFD_TEST',
            'version': 1,
            'format': 'native_batch',
            'exchanges': {
                'nse_cm': {
                    'value': NSE_CM,
                    'divider': 100,
                },
                'cde_fo': {
                    'value': CDE_FO,
                    'divider': 10000000,
                },
                'mcx_fo': {
                    'value': MCX_FO,
                    'divider': 100,
                },
            },
        })

    def refusal(self):
        """Kotak's refusal of the session, which repeats the session id.

        Returns:
            str: The message.
        """
        return json.dumps({
            'message_code': 1120,
            'message': 'Auth failed Matrix Auth failed V0RTT sid-token-1 NEOTRADEAPI 100000 "ok" false null',
        })

    def acknowledgement(self, trading_symbols, description='SUBSCRIBED', error_code=0):
        """The subscription acknowledgement.

        Args:
            trading_symbols (dict): `EXCHANGE|TOKEN` to trading symbol.
            description (str): Kotak's description of the outcome.
            error_code (int): Kotak's error code, 0 when subscribed.

        Returns:
            str: The message.
        """
        return json.dumps({
            'message_code': 1109,
            'error_code': error_code,
            'description': description,
            'trading_symbols': trading_symbols,
        })

    def market_picture(self, exchange_id, token, last_price, close, buy_rows, sell_rows, level=8, declared_rows=None):
        """A market picture packet, prices in the exchange's integer units.

        Args:
            exchange_id (int): The exchange id.
            token (int): The instrument's token.
            last_price (int): The last price.
            close (int): The previous close.
            buy_rows (list): Buy rows as (quantity, price, orders), best first.
            sell_rows (list): Sell rows as (quantity, price, orders), best first.
            level (int): The packet's level.
            declared_rows (tuple | None): The buy and sell row counts to declare, when they should differ from the rows given.

        Returns:
            bytes: The packet, its length first.
        """
        buy_count = len(buy_rows)
        sell_count = len(sell_rows)
        if declared_rows is not None:
            buy_count, sell_count = declared_rows
        body = MARKET_PICTURE.pack(
            token,
            5400,
            6100,
            1200000,
            1790316328,
            1790316329,
            max(last_price - 500, 0),
            close,
            last_price + 1000,
            max(last_price - 900, 0),
            last_price,
            25,
            max(last_price - 150, 0),
            0,
            buy_count,
            sell_count,
            0,
            0,
            12000 if exchange_id == MCX_FO else 0,
            0.0,
            last_price - close,
            0,
            0,
            0,
            0,
            1,
            2,
            1,
        )
        for quantity, price, orders in buy_rows + sell_rows:
            body = body + DEPTH_ROW.pack(quantity, price, orders)
        return self.packet(MARKET_PICTURE_CODE, exchange_id, level, body)

    def packet(self, message_code, exchange_id, level, body):
        """A packet: its length, its header and its body.

        Args:
            message_code (int): The message code.
            exchange_id (int): The exchange id.
            level (int): The level.
            body (bytes): Everything after the header.

        Returns:
            bytes: The packet.
        """
        length = PACKET_HEADER.size + len(body)
        return PACKET_HEADER.pack(length, message_code, exchange_id, level, 0, 0, 0) + body

    def depth_rows(self, best_price, step):
        """Five depth rows.

        Args:
            best_price (int): The best price.
            step (int): How far each further level is from the one before.

        Returns:
            list: Rows as (quantity, price, orders).
        """
        rows = []
        for level in range(5):
            rows.append((10 + level, best_price + level * step, 1 + level))
        return rows


class KotakFeedCases:
    """Every Kotak scenario, and how each socket is built the way its script builds it.

    Attributes:
        loader (harness.ScriptLoader): Loads the two scripts.
        messages (KotakFeedMessages): Builds SFeed messages.
    """

    def __init__(self, loader):
        """Keeps the script loader.

        Args:
            loader (harness.ScriptLoader): Loads the two scripts.

        Returns:
            None: This method returns nothing.
        """
        self.loader = loader
        self.messages = KotakFeedMessages()

    def stub_modules(self, context):
        """The modules replaced while a Kotak scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        api_module = types.ModuleType('stock_brokers.api.kotak')
        api_module.KotakAPI = StubKotakAPI
        return {
            'stock_brokers.api.kotak': api_module,
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
            kotak_websockets,
        ]

    def build_quotes_socket(self, context, instrument_tokens, names):
        """Builds a quotes socket the way `bin/kotak/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            instrument_tokens (list): The `EXCHANGE|TOKEN` instruments.
            names (dict): Instruments to trading symbols, which the socket adds to.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = kotak_websockets.KotakSession(context.logger)
        store = script.KotakQuotesStore(context.redis)
        socket = kotak_websockets.KotakQuotesSocket(
            'socket_0',
            instrument_tokens,
            names,
            session,
            store.write_name,
            store.write_ticks,
            context.logger,
        )
        context.use_instant_waits(socket)
        return socket

    def build_order_socket(self, context):
        """Builds an order updates socket the way `bin/kotak/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        session = kotak_websockets.KotakSession(context.logger)
        store = script.KotakOrderUpdatesStore(context.redis, context.logger)
        socket = kotak_websockets.KotakOrderUpdatesSocket(session, store.write_updates, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every Kotak scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        refused = [
            ('open',),
            ('message', self.messages.authentication_answer(1119)),
            ('message', self.messages.refusal()),
        ]
        order_refused = [
            ('open',),
            ('message', json.dumps({'ak': 'nk', 'type': 'failed to connect', 'msg': 'Invalid session'})),
        ]
        return [
            (
                'kotak.quotes.every_frame_shape',
                [
                    self.every_frame_connection(),
                ],
                set(),
                self.run_quotes,
            ),
            (
                'kotak.quotes.connection_refused_logs_in_again',
                [
                    refused + [('close', None, None)],
                    [
                        ('open',),
                        ('message', self.messages.authentication_answer(1119)),
                        ('message', self.messages.acknowledgement({})),
                        ('message', self.messages.market_picture(NSE_CM, 11536, 385000, 380000, [], [])),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'kotak.quotes.no_session_id_logs_in_again',
                [
                    [
                        ('open',),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_without_a_session_id,
            ),
            (
                'kotak.quotes.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('message', self.messages.authentication_answer(1119)),
                        ('call', self.log_in_elsewhere),
                        ('message', self.messages.refusal()),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'kotak.quotes.refused_again_logs_in_again',
                [
                    refused,
                    refused,
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'kotak.quotes.stored_feed_url',
                [
                    [
                        ('open',),
                        ('message', self.messages.authentication_answer(1119)),
                        ('message', self.messages.acknowledgement({})),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes_with_a_stored_feed_url,
            ),
            (
                'kotak.quotes.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_quotes,
            ),
            (
                'kotak.quotes.login_again_fails',
                [
                    refused,
                ],
                {
                    2,
                },
                self.run_quotes,
            ),
            (
                'kotak.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes,
            ),
            (
                'kotak.orders.updates',
                [
                    self.every_order_message_connection(),
                ],
                set(),
                self.run_orders,
            ),
            (
                'kotak.orders.refusal_drops_the_frame',
                [
                    [
                        ('open',),
                        ('message', json.dumps([{'type': 'order', 'data': self.kotak_order('260925000000009', 'complete')}, {'ak': 'nk', 'type': 'failed to connect', 'msg': 'Invalid session'}])),
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
                'kotak.orders.no_host_fails_the_connect',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders_without_a_host,
            ),
            (
                'kotak.orders.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', json.dumps({'ak': 'nk', 'type': 'failed to connect', 'msg': 'Invalid session'})),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'kotak.orders.refused_again_gives_up',
                [
                    order_refused,
                    order_refused,
                ],
                set(),
                self.run_orders,
            ),
            (
                'kotak.orders.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_orders,
            ),
            (
                'kotak.orders.login_again_fails',
                [
                    order_refused,
                ],
                {
                    2,
                },
                self.run_orders,
            ),
            (
                'kotak.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders,
            ),
        ]

    def every_frame_connection(self):
        """One connection carrying every SFeed message and packet shape the quotes decoder handles.

        Returns:
            list: The scripted steps.
        """
        tcs_rows = self.messages.depth_rows(384990, -5) + self.messages.depth_rows(385010, 5)
        held = self.messages.market_picture(NSE_CM, 11536, 385000, 380000, tcs_rows[:5], tcs_rows[5:])
        held = held + self.messages.market_picture(MCX_FO, 426016, 612300, 609900, [(3, 612250, 2)], [(4, 612350, 1)])
        after = self.messages.market_picture(NSE_CM, 11536, 385050, 380000, tcs_rows[:5], tcs_rows[5:])
        after = after + self.messages.packet(CLOSING_AUCTION_CODE, NSE_CM, 8, struct.pack('<IIqq', 11536, 385000, 100, 0) + bytes(150))
        after = after + self.messages.market_picture(NSE_CM, 11536, 385100, 380000, tcs_rows[:5], tcs_rows[5:])
        after = after + self.messages.market_picture(NSE_CM, 2885, 0, 0, [], [])
        after = after + self.messages.market_picture(CDE_FO, 10465, 831250000, 830000000, [(1, 831200000, 1)], [(2, 831300000, 1)], level=4)
        after = after + self.messages.market_picture(42, 7, 100, 100, [], [])
        after = after + self.messages.market_picture(NSE_CM, 1594, 150000, 149000, [(5, 149990, 1)], [(6, 150010, 1)], declared_rows=(5, 5))
        after = after + self.messages.packet(MARKET_PICTURE_CODE, NSE_CM, 8, b'short')
        after = after + bytes([200, 0, 1])
        return [
            ('open',),
            ('message', self.messages.authentication_answer(1119)),
            ('message', self.messages.authentication_answer(1117)),
            ('message', held),
            ('message', self.messages.acknowledgement({'nse_cm|11536': 'TCS-EQ', 'mcx_fo|426016': 'CRUDEOIL26OCTFUT', 'nse_cm|2885': 'RELIANCE-EQ', 'nse_cm|1594': ''})),
            ('message', after),
            ('message', self.messages.acknowledgement({}, 'NOT SUBSCRIBED', 3)),
            ('message', json.dumps({'message_code': 1999, 'detail': 'something new'})),
            ('message', json.dumps(['not', 'an', 'object'])),
            ('message', 'a text frame'),
            ('message', b'\x00'),
            ('close', 1000, 'normal closure'),
        ]

    def every_order_message_connection(self):
        """One connection carrying every kind of message the order decoder handles.

        Returns:
            list: The scripted steps.
        """
        without_number = self.kotak_order('', 'open')
        without_key = self.kotak_position('')
        without_key['tok'] = ''
        without_key['trdSym'] = ''
        return [
            ('open',),
            ('message', json.dumps({'ak': 'ok', 'type': 'cn', 'task': 'cn', 'msg': 'connected'})),
            ('message', json.dumps({'type': 'order', 'data': self.kotak_order('260925000000001', 'complete')})),
            ('message', json.dumps([{'type': 'order', 'data': self.kotak_order('260925000000002', 'open')}, {'type': 'order', 'data': without_number}, {'type': 'position', 'data': self.kotak_position('11536')}, {'type': 'position', 'data': without_key}, {'type': 'heartbeat'}, 'not a dictionary'])),
            ('message', json.dumps({'type': 'position', 'data': self.kotak_position('2885')}).encode('utf-8')),
            ('message', 'not json'),
            ('close', 1000, 'normal closure'),
        ]

    def run_quotes(self, context):
        """Builds a quotes socket for three instruments, one named, and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built, and the names the socket learned.
        """
        instrument_tokens = [
            'mcx_fo|426016',
            'nse_cm|11536',
            'nse_cm|2885',
            'cde_fo|10465',
            'nse_cm|1594',
        ]
        names = {
            'nse_cm|11536': 'TCS-EQ',
        }
        try:
            socket = self.build_quotes_socket(context, instrument_tokens, names)
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
            'names': names,
        }

    def run_quotes_without_a_session_id(self, context):
        """Runs a quotes socket whose stored login has no session id when it first opens.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        instrument_tokens = [
            'nse_cm|11536',
        ]
        try:
            socket = self.build_quotes_socket(context, instrument_tokens, {})
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        context.logins.replace_elsewhere('nosid-token')
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }

    def run_quotes_with_a_stored_feed_url(self, context):
        """Runs a quotes socket whose stored login names its own market feed address.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        instrument_tokens = [
            'nse_cm|11536',
        ]
        try:
            socket = self.build_quotes_socket(context, instrument_tokens, {})
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        context.logins.replace_elsewhere('feedurl-token')
        socket.run_forever()
        return {
            'gave_up': socket.gave_up,
        }

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

    def run_orders_without_a_host(self, context):
        """Runs an order socket whose stored login has no host until it logs in again.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        try:
            socket = self.build_order_socket(context)
        except RuntimeError as error:
            return {
                'build_error': str(error),
            }
        context.logins.replace_elsewhere('nobaseurl-token')
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

    def kotak_order(self, order_number, status):
        """An order as Kotak sends it in an order message's `data`.

        Args:
            order_number (str): The order number.
            status (str): Kotak's status.

        Returns:
            dict: The order.
        """
        return {
            'nOrdNo': order_number,
            'exOrdId': '1100000012345678',
            'ordSt': status,
            'rejRsn': '',
            'trdSym': 'TCS-EQ',
            'sym': 'TCS',
            'exSeg': 'nse_cm',
            'tok': '11536',
            'trnsTp': 'B',
            'prcTp': 'L',
            'prod': 'CNC',
            'vldt': 'DAY',
            'qty': '10',
            'fldQty': '4',
            'unFldSz': '6',
            'prc': '3850.00',
            'trgPrc': '0.00',
            'avgPrc': '3849.90',
            'ordDtTm': '25-Sep-2026 10:15:29',
            'exCfmTm': '25-Sep-2026 10:15:29',
        }

    def kotak_position(self, token):
        """A position as Kotak sends it in a position message's `data`.

        Args:
            token (str): The instrument token.

        Returns:
            dict: The position.
        """
        return {
            'trdSym': 'TCS-EQ',
            'sym': 'TCS',
            'exSeg': 'nse_cm',
            'tok': token,
            'prod': 'MIS',
            'flBuyQty': '10',
            'flSellQty': '4',
            'buyAmt': '38499.00',
            'sellAmt': '15402.00',
            'lotSz': '1',
            'multiplier': '1',
            'hsUpTm': '2026/09/25 10:15:29',
        }
