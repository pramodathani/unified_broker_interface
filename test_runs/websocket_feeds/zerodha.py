"""The Zerodha quotes and order updates sockets, driven through scripted Kite connections."""

import json
import struct
import types

from stock_brokers.websockets import zerodha as zerodha_websockets
from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/zerodha/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/zerodha/orders/websocket_order_details'

RELIANCE_TOKEN = 738561
INFY_TOKEN = 408065
NIFTY_TOKEN = 256265
USDINR_TOKEN = 4099
BSE_CURRENCY_TOKEN = 8198
CRUDE_TOKEN = 12295


class StubZerodhaAPI:
    """A stand-in for `ZerodhaAPI` whose construction is a login recorded in the scenario's ledger.

    Attributes:
        logins (harness.LoginLedger): The ledger of the scenario being run, set before each scenario.
    """

    logins = None

    def __init__(self):
        """Logs in, as constructing the real class does when the stored session is dead.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the ledger scripts this login to fail.
        """
        StubZerodhaAPI.logins.log_in()
        self._settings = {
            'api_key': 'kite-api-key',
        }

    def _current_login(self):
        """The login in force now, as the Redis `last_login` hash would hold it.

        Returns:
            dict | None: The access token in force, or None before any login.
        """
        if StubZerodhaAPI.logins.current_token is None:
            return None
        return {
            'access_token': StubZerodhaAPI.logins.current_token,
        }


class KitePackets:
    """Builds Kite ticker frames byte by byte, the way `wss://ws.kite.trade` sends them."""

    def integers(self, *values):
        """Packs unsigned big endian four byte integers.

        Args:
            *values (int): The integers.

        Returns:
            bytes: The packed integers.
        """
        packed = b''
        for value in values:
            packed = packed + struct.pack('>I', value)
        return packed

    def last_price(self, token, price):
        """An 8 byte last price packet.

        Args:
            token (int): The instrument token.
            price (int): The price in Kite's integer units.

        Returns:
            bytes: The packet.
        """
        return self.integers(token, price)

    def index_quote(self, token, last, high, low, opening, close, with_timestamp):
        """A 28 byte index quote, or a 32 byte one with the exchange timestamp.

        Args:
            token (int): The index token.
            last (int): The last price.
            high (int): The day's high.
            low (int): The day's low.
            opening (int): The day's open.
            close (int): The previous close.
            with_timestamp (bool): Whether to add the timestamp.

        Returns:
            bytes: The packet.
        """
        packet = self.integers(token, last, high, low, opening, close, 1500)
        if with_timestamp:
            packet = packet + self.integers(1790316329)
        return packet

    def quote(self, token, last, close):
        """A 44 byte quote packet.

        Args:
            token (int): The instrument token.
            last (int): The last price.
            close (int): The previous close.

        Returns:
            bytes: The packet.
        """
        return self.integers(
            token,
            last,
            25,
            last - 3,
            120000,
            5400,
            6100,
            last - 40,
            last + 60,
            last - 90,
            close,
        )

    def full(self, token, last, close):
        """A 184 byte full packet with open interest and five levels of depth on each side.

        Args:
            token (int): The instrument token.
            last (int): The last price.
            close (int): The previous close.

        Returns:
            bytes: The packet.
        """
        packet = self.quote(token, last, close)
        packet = packet + self.integers(1790316328, 88000, 91000, 87000, 1790316329)
        for level in range(10):
            packet = packet + struct.pack('>IIHH', 100 + level, last - 5 + level, 3 + level, 0)
        return packet

    def frame(self, packets):
        """A binary frame: the packet count, then each packet after its two byte length.

        Args:
            packets (list): The packets.

        Returns:
            bytes: The frame.
        """
        frame = struct.pack('>H', len(packets))
        for packet in packets:
            frame = frame + struct.pack('>H', len(packet)) + packet
        return frame


class ZerodhaFeedCases:
    """Every Zerodha scenario, and how each socket is built the way its script builds it.

    Attributes:
        loader (harness.ScriptLoader): Loads the two scripts.
        packets (KitePackets): Builds Kite frames.
    """

    def __init__(self, loader):
        """Keeps the script loader.

        Args:
            loader (harness.ScriptLoader): Loads the two scripts.

        Returns:
            None: This method returns nothing.
        """
        self.loader = loader
        self.packets = KitePackets()

    def stub_modules(self, context):
        """The modules replaced while a Zerodha scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        StubZerodhaAPI.logins = context.logins
        api_module = types.ModuleType('stock_brokers.api.zerodha')
        api_module.ZerodhaAPI = StubZerodhaAPI
        return {
            'stock_brokers.api.zerodha': api_module,
        }

    def datetime_holders(self):
        """The modules whose `datetime` name is frozen while a scenario runs.

        Returns:
            list: The modules.
        """
        return [
            self.loader.load(ORDERS_SCRIPT),
            zerodha_websockets,
        ]

    def build_quotes_socket(self, context, tokens, names):
        """Builds a quotes socket the way `bin/zerodha/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The instrument tokens to subscribe to.
            names (dict): Tokens, as text, to instrument names.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = zerodha_websockets.ZerodhaSession(context.logger)
        store = script.ZerodhaQuotesStore(context.redis)
        socket = zerodha_websockets.ZerodhaQuotesSocket(
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
        """Builds an order updates socket the way `bin/zerodha/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        session = zerodha_websockets.ZerodhaSession(context.logger)
        store = script.ZerodhaOrderUpdatesStore(context.redis, context.logger)
        socket = zerodha_websockets.ZerodhaOrderUpdatesSocket(session, store.write_updates, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every Zerodha scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        refused = harness.FakeWebsocketError('Handshake status 403 Forbidden', status_code=403)
        return [
            (
                'zerodha.quotes.every_packet_shape',
                [
                    [
                        ('open',),
                        ('message', self.every_packet_shape_frame()),
                        ('message', self.packets.frame([])[:1]),
                        ('message', struct.pack('>H', 3) + struct.pack('>H', 8) + self.packets.last_price(INFY_TOKEN, 150000)),
                        ('message', json.dumps({'type': 'error', 'data': 'Invalid token'})),
                        ('message', json.dumps({'type': 'message', 'data': 'Hello'})),
                        ('message', 'not json'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'zerodha.quotes.refused_then_logs_in_again',
                [
                    [
                        ('error', refused),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'zerodha.quotes.token_replaced_elsewhere',
                [
                    [
                        ('call', self.log_in_elsewhere),
                        ('error', refused),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'zerodha.quotes.refused_again_gives_up',
                [
                    [
                        ('error', refused),
                    ],
                    [
                        ('error', refused),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'zerodha.quotes.failed_connects_give_up',
                self.failed_connects(12),
                set(),
                self.run_quotes,
            ),
            (
                'zerodha.quotes.login_again_fails',
                [
                    [
                        ('error', refused),
                    ],
                ],
                {
                    2,
                },
                self.run_quotes,
            ),
            (
                'zerodha.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes,
            ),
            (
                'zerodha.orders.updates',
                [
                    [
                        ('open',),
                        ('message', json.dumps({'type': 'order', 'data': self.kite_order('260925000000001', 'COMPLETE')})),
                        ('message', json.dumps(self.mixed_messages())),
                        ('message', b'\x00\x01\x00\x08binary'),
                        ('message', 'not json'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'zerodha.orders.refused_then_logs_in_again',
                [
                    [
                        ('error', refused),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'zerodha.orders.token_replaced_elsewhere',
                [
                    [
                        ('call', self.log_in_elsewhere),
                        ('error', refused),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'zerodha.orders.refused_again_gives_up',
                [
                    [
                        ('error', refused),
                    ],
                    [
                        ('error', refused),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'zerodha.orders.failed_connects_give_up',
                self.failed_connects(12),
                set(),
                self.run_orders,
            ),
            (
                'zerodha.orders.login_again_fails',
                [
                    [
                        ('error', refused),
                    ],
                ],
                {
                    2,
                },
                self.run_orders,
            ),
            (
                'zerodha.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders,
            ),
        ]

    def run_quotes(self, context):
        """Builds a quotes socket for three named and four unnamed instruments and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        tokens = [
            RELIANCE_TOKEN,
            INFY_TOKEN,
            NIFTY_TOKEN,
            USDINR_TOKEN,
            BSE_CURRENCY_TOKEN,
            CRUDE_TOKEN,
        ]
        names = {
            str(RELIANCE_TOKEN): 'NSE:RELIANCE',
            str(NIFTY_TOKEN): 'NSE:NIFTY 50',
            str(CRUDE_TOKEN): 'MCX:CRUDEOIL26OCTFUT',
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
        StubZerodhaAPI.logins.replace_elsewhere('token-from-another-process')

    def failed_connects(self, count):
        """Connection attempts that each fail before opening.

        Args:
            count (int): How many attempts fail.

        Returns:
            list: One scripted connection per attempt.
        """
        connections = []
        for _ in range(count):
            connections.append(
                [
                    ('raise', ConnectionRefusedError(111, 'Connection refused')),
                ]
            )
        return connections

    def every_packet_shape_frame(self):
        """One frame holding every packet shape the decoder has a branch for.

        Returns:
            bytes: The frame.
        """
        return self.packets.frame(
            [
                self.packets.last_price(INFY_TOKEN, 150025),
                self.packets.index_quote(NIFTY_TOKEN, 2512345, 2520000, 2490000, 2500000, 2495000, False),
                self.packets.index_quote(NIFTY_TOKEN, 2512345, 2520000, 2490000, 2500000, 2495000, True),
                self.packets.quote(RELIANCE_TOKEN, 295050, 293000),
                self.packets.full(RELIANCE_TOKEN, 295075, 293000),
                self.packets.full(USDINR_TOKEN, 835012500, 834000000),
                self.packets.quote(BSE_CURRENCY_TOKEN, 8350125, 0),
                self.packets.full(CRUDE_TOKEN, 612300, 609900),
                self.packets.integers(INFY_TOKEN, 150000, 1, 2, 3),
                self.packets.integers(INFY_TOKEN),
            ]
        )

    def kite_order(self, order_id, status):
        """An order as Kite sends it, both in the order book and as an order update's `data`.

        Args:
            order_id (str): The order id.
            status (str): Kite's status.

        Returns:
            dict: The order.
        """
        return {
            'order_id': order_id,
            'exchange_order_id': '1100000012345678',
            'parent_order_id': None,
            'status': status,
            'status_message': None,
            'tradingsymbol': 'RELIANCE',
            'exchange': 'NSE',
            'instrument_token': RELIANCE_TOKEN,
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'product': 'CNC',
            'validity': 'DAY',
            'variety': 'regular',
            'quantity': 5,
            'filled_quantity': 5,
            'pending_quantity': 0,
            'cancelled_quantity': 0,
            'disclosed_quantity': 0,
            'price': 2950.5,
            'trigger_price': 0,
            'average_price': 2950.4,
            'order_timestamp': '2026-09-25 10:15:29',
            'exchange_timestamp': '2026-09-25 10:15:29',
            'tag': 'ubi',
        }

    def mixed_messages(self):
        """A list payload holding two orders, one order without an id, an error and a message of another type.

        Returns:
            list: The payload.
        """
        order_without_id = self.kite_order('', 'OPEN')
        order_without_id['order_id'] = None
        return [
            {
                'type': 'order',
                'data': self.kite_order('260925000000002', 'OPEN'),
            },
            {
                'type': 'order',
                'data': self.kite_order('260925000000003', 'REJECTED'),
            },
            {
                'type': 'order',
                'data': order_without_id,
            },
            {
                'type': 'error',
                'data': 'Something went wrong',
            },
            {
                'type': 'message',
                'data': 'Hello',
            },
            'not a dictionary',
        ]
