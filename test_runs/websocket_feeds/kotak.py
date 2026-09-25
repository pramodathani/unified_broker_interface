"""The Kotak quotes and order updates sockets, driven through scripted HSM and realtime connections."""

import json
import types

from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/kotak/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/kotak/orders/websocket_order_details'

CONNECTION_FRAME = 1
SUBSCRIBE_FRAME = 4
DATA_FRAME = 6
SNAPSHOT_PACKET = 83
UPDATE_PACKET = 85
UNCHANGED = -2147483648


class StubKotakAPI(harness.StubBrokerAPI):
    """A stand-in for `KotakAPI`, whose login carries a session id and the account's host as Kotak's does.

    A ledger token starting with `nosid` has no session id, and one starting with `nobaseurl` has no host.
    """

    def _current_login(self):
        """The login in force now.

        Returns:
            dict | None: The access token, session id and host, or None before any login.
        """
        token = harness.StubBrokerAPI.logins.current_token
        if token is None:
            return None
        login = {
            'access_token': token,
            'sid': f'sid-{token}',
            'base_url': 'https://e21.kotaksecurities.com/',
        }
        if token.startswith('nosid'):
            login['sid'] = None
        if token.startswith('nobaseurl'):
            login['base_url'] = None
        return login


class KotakFrames:
    """Builds the binary frames of Kotak's HSM feed, big endian, as `wss://mlhsm.kotaksecurities.com` sends them."""

    def framed(self, frame_type, body):
        """A frame: its length, its type and its body.

        Args:
            frame_type (int): The frame type.
            body (bytes): Everything after the type.

        Returns:
            bytes: The frame.
        """
        content = bytes([frame_type]) + body
        return len(content).to_bytes(2, 'big') + content

    def status_field(self, status):
        """A status field: id 1, a two-byte length and the status.

        Args:
            status (str): The status letter.

        Returns:
            bytes: The field.
        """
        return bytes([1]) + len(status).to_bytes(2, 'big') + status.encode('latin-1')

    def connection_response(self, status, acknowledge_every):
        """A connection response.

        Args:
            status (str): `K` for accepted.
            acknowledge_every (int | None): After how many data frames Kotak wants an acknowledgement, or None to leave the field out.

        Returns:
            bytes: The frame.
        """
        if acknowledge_every is None:
            return self.framed(CONNECTION_FRAME, bytes([1]) + self.status_field(status))
        acknowledgement = bytes([2]) + (4).to_bytes(2, 'big') + acknowledge_every.to_bytes(4, 'big')
        return self.framed(CONNECTION_FRAME, bytes([2]) + self.status_field(status) + acknowledgement)

    def subscription_response(self, status):
        """A subscription response.

        Args:
            status (str): `K` for accepted.

        Returns:
            bytes: The frame.
        """
        return self.framed(SUBSCRIBE_FRAME, bytes([1]) + self.status_field(status))

    def numbers(self, values):
        """Numeric fields, four signed bytes each, with None as Kotak's unchanged marker.

        Args:
            values (list): The values.

        Returns:
            bytes: The packed values.
        """
        packed = bytes([len(values)])
        for value in values:
            if value is None:
                value = UNCHANGED
            packed = packed + value.to_bytes(4, 'big', signed=True)
        return packed

    def snapshot(self, topic_id, topic_name, values, strings):
        """A snapshot packet.

        Args:
            topic_id (int): The topic id updates refer to.
            topic_name (str): The topic name, such as `sf|nse_cm|11536`.
            values (list): The numeric fields in field order.
            strings (dict): String fields by field id.

        Returns:
            bytes: The packet, after its two-byte length.
        """
        name = topic_name.encode('latin-1')
        body = bytes([SNAPSHOT_PACKET]) + topic_id.to_bytes(4, 'big', signed=True) + bytes([len(name)]) + name + self.numbers(values)
        body = body + bytes([len(strings)])
        for field_id, text in strings.items():
            encoded = text.encode('latin-1')
            body = body + bytes([field_id, len(encoded)]) + encoded
        return len(body).to_bytes(2, 'big') + body

    def update(self, topic_id, values):
        """An update packet.

        Args:
            topic_id (int): The topic id.
            values (list): The numeric fields in field order.

        Returns:
            bytes: The packet, after its two-byte length.
        """
        body = bytes([UPDATE_PACKET]) + topic_id.to_bytes(4, 'big', signed=True) + self.numbers(values)
        return len(body).to_bytes(2, 'big') + body

    def data(self, message_number, packets, declared_count=None):
        """A data frame.

        Args:
            message_number (int | None): The message number, or None when acknowledgements were not asked for.
            packets (list): The packets.
            declared_count (int | None): The packet count to declare, when it should differ from the packets given.

        Returns:
            bytes: The frame.
        """
        count = len(packets)
        if declared_count is not None:
            count = declared_count
        body = b''
        if message_number is not None:
            body = message_number.to_bytes(4, 'big', signed=True)
        body = body + count.to_bytes(2, 'big')
        for packet in packets:
            body = body + packet
        return self.framed(DATA_FRAME, body)


class KotakFeedCases:
    """Every Kotak scenario, and how each socket is built the way its script builds it.

    Attributes:
        loader (harness.ScriptLoader): Loads the two scripts.
        frames (KotakFrames): Builds HSM frames.
    """

    def __init__(self, loader):
        """Keeps the script loader.

        Args:
            loader (harness.ScriptLoader): Loads the two scripts.

        Returns:
            None: This method returns nothing.
        """
        self.loader = loader
        self.frames = KotakFrames()

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
        session = script.KotakSession(context.logger)
        socket = script.QuotesSocket('socket_0', instrument_tokens, names, session, context.redis, context.logger)
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
        socket = script.OrderUpdatesSocket(context.redis, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every Kotak scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        refused = [
            ('open',),
            ('message', self.frames.connection_response('N', None)),
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
                        ('message', self.frames.connection_response('K', None)),
                        ('message', self.frames.data(None, [self.frames.snapshot(1, 'sf|nse_cm|11536', [0, 0, 1790316329, 1790316328, 1000, 385000], {})])),
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
                        ('call', self.log_in_elsewhere),
                        ('message', self.frames.connection_response('N', None)),
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

    def scrip_values(self, last_price, close, open_interest):
        """A scrip topic's numeric fields, 25 of them, in field order.

        Args:
            last_price (int): The last price, in paise.
            close (int): The previous close, in paise.
            open_interest (int | None): The open interest, or None for unchanged.

        Returns:
            list: The fields.
        """
        values = []
        for _ in range(25):
            values.append(0)
        values[2] = 1790316329
        values[3] = 1790316328
        values[4] = 1200000
        values[5] = last_price
        values[6] = 25
        values[7] = 5400
        values[8] = 6100
        values[13] = last_price - 150
        values[14] = last_price - 900
        values[15] = last_price + 1000
        values[20] = last_price - 500
        values[21] = close
        values[22] = open_interest
        values[23] = 1
        values[24] = 2
        return values

    def depth_values(self):
        """A depth topic's numeric fields, 34 of them, in field order.

        Returns:
            list: The fields.
        """
        values = []
        for _ in range(34):
            values.append(0)
        for level in range(5):
            values[2 + level] = 385000 - level * 5
            values[7 + level] = 385010 + level * 5
            values[12 + level] = 10 + level
            values[17 + level] = 20 + level
            values[22 + level] = 1 + level
            values[27 + level] = 2 + level
        values[6] = None
        values[16] = None
        values[32] = 1
        values[33] = 2
        return values

    def every_frame_connection(self):
        """One connection carrying every HSM frame and packet shape the quotes decoder handles.

        Returns:
            list: The scripted steps.
        """
        first = self.frames.data(
            1,
            [
                self.frames.snapshot(10, 'sf|nse_cm|11536', self.scrip_values(385000, 380000, None), {54: 'TCS-EQ'}),
                self.frames.snapshot(11, 'sf|mcx_fo|426016', self.scrip_values(612300, 609900, 12000), {54: 'CRUDEOIL26OCTFUT'}),
                self.frames.snapshot(12, 'dp|nse_cm|11536', self.depth_values(), {}),
                self.frames.update(10, [None, None, 1790316330, None, None, 385050]),
            ],
        )
        second = self.frames.data(
            2,
            [
                self.frames.update(99, [1, 2]),
                self.frames.snapshot(13, 'xx|nse_cm|1', [1], {}),
                self.frames.snapshot(14, 'sf|nse_cm|2885', [0, 0, 0, 0, 0, None], {54: 'RELIANCE-EQ'}),
                bytes([0, 1, 99]),
                self.frames.update(10, [1]),
            ],
        )
        truncated = self.frames.data(3, [self.frames.update(11, [None, None, None, None, None, 612400])], declared_count=2)
        return [
            ('open',),
            ('message', self.frames.connection_response('K', 2)),
            ('message', self.frames.subscription_response('K')),
            ('message', self.frames.subscription_response('N')),
            ('message', self.frames.framed(SUBSCRIBE_FRAME, bytes([0]))),
            ('message', first),
            ('message', second),
            ('message', truncated),
            ('message', self.frames.framed(9, b'unknown')),
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
