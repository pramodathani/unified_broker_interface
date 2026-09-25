"""The Dhan quotes and order updates sockets, driven through scripted DhanHQ connections."""

import json
import struct
import types

from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/dhan/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/dhan/orders/websocket_order_details'

INDEX_SEGMENT = 0
EQUITY_SEGMENT = 1
FUTURES_SEGMENT = 2
COMMODITY_SEGMENT = 5

TICKER = 2
QUOTE = 4
OPEN_INTEREST = 5
PREVIOUS_CLOSE = 6
FULL = 8
DISCONNECT = 50

HDFC_BANK = 1333
NIFTY = 13
NIFTY_FUTURE = 35001
CRUDE_FUTURE = 426016


class StubDhanAPI(harness.StubBrokerAPI):
    """A stand-in for `DhanAPI`.

    Attributes:
        SETTINGS (dict): The client id the sockets send with the token.
    """

    SETTINGS = {
        'client_id': '1100012345',
    }


class DhanPackets:
    """Builds DhanHQ market feed packets, little endian, the way `wss://api-feed.dhan.co` sends them."""

    def header(self, feed_code, length, segment, security_id):
        """The eight byte header every packet opens with.

        Args:
            feed_code (int): The response code.
            length (int): The packet's whole length.
            segment (int): Dhan's numeric exchange segment.
            security_id (int): The security id.

        Returns:
            bytes: The header.
        """
        return struct.pack('<BhBi', feed_code, length, segment, security_id)

    def ticker(self, segment, security_id, price, trade_time):
        """A 16 byte ticker packet.

        Args:
            segment (int): The segment.
            security_id (int): The security id.
            price (float): The last price.
            trade_time (int): The last trade time, as India wall clock seconds.

        Returns:
            bytes: The packet.
        """
        return self.header(TICKER, 16, segment, security_id) + struct.pack('<fi', price, trade_time)

    def trade_fields(self, price):
        """The trade fields the quote and full packets share, bytes 8 to 34.

        Args:
            price (float): The last price.

        Returns:
            bytes: The 26 bytes.
        """
        return struct.pack('<fhifiii', price, 25, 1790331329, price - 1.5, 120000, 5400, 6100)

    def quote(self, segment, security_id, price, close):
        """A 50 byte quote packet.

        Args:
            segment (int): The segment.
            security_id (int): The security id.
            price (float): The last price.
            close (float): The close in the packet.

        Returns:
            bytes: The packet.
        """
        return (
            self.header(QUOTE, 50, segment, security_id)
            + self.trade_fields(price)
            + struct.pack('<ffff', price - 10, close, price + 20, price - 30)
        )

    def full(self, segment, security_id, price, close):
        """A 162 byte full packet with open interest and five levels of depth on each side.

        Args:
            segment (int): The segment.
            security_id (int): The security id.
            price (float): The last price.
            close (float): The close in the packet.

        Returns:
            bytes: The packet.
        """
        packet = (
            self.header(FULL, 162, segment, security_id)
            + self.trade_fields(price)
            + struct.pack('<iii', 88000, 91000, 87000)
            + struct.pack('<ffff', price - 10, close, price + 20, price - 30)
        )
        for level in range(5):
            packet = packet + struct.pack('<iihhff', 100 + level, 200 + level, 3 + level, 4 + level, price - level, price + level)
        return packet

    def open_interest(self, segment, security_id, open_interest):
        """A 12 byte open interest packet.

        Args:
            segment (int): The segment.
            security_id (int): The security id.
            open_interest (int): The open interest.

        Returns:
            bytes: The packet.
        """
        return self.header(OPEN_INTEREST, 12, segment, security_id) + struct.pack('<i', open_interest)

    def previous_close(self, segment, security_id, close):
        """A 16 byte previous close packet.

        Args:
            segment (int): The segment.
            security_id (int): The security id.
            close (float): The previous session's close.

        Returns:
            bytes: The packet.
        """
        return self.header(PREVIOUS_CLOSE, 16, segment, security_id) + struct.pack('<fi', close, 77000)

    def disconnect(self, code):
        """A 10 byte disconnect packet.

        Args:
            code (int): The disconnect reason code.

        Returns:
            bytes: The packet.
        """
        return self.header(DISCONNECT, 10, EQUITY_SEGMENT, HDFC_BANK) + struct.pack('<h', code)


class DhanFeedCases:
    """Every Dhan scenario, and how each socket is built the way its script builds it.

    Attributes:
        loader (harness.ScriptLoader): Loads the two scripts.
        packets (DhanPackets): Builds Dhan packets.
    """

    def __init__(self, loader):
        """Keeps the script loader.

        Args:
            loader (harness.ScriptLoader): Loads the two scripts.

        Returns:
            None: This method returns nothing.
        """
        self.loader = loader
        self.packets = DhanPackets()

    def stub_modules(self, context):
        """The modules replaced while a Dhan scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        api_module = types.ModuleType('stock_brokers.api.dhan')
        api_module.DhanAPI = StubDhanAPI
        return {
            'stock_brokers.api.dhan': api_module,
        }

    def datetime_holders(self):
        """The modules whose `datetime` name is frozen while a scenario runs.

        Returns:
            list: The modules.
        """
        return [
            self.loader.load(ORDERS_SCRIPT),
        ]

    def build_quotes_socket(self, context, tokens, names):
        """Builds a quotes socket the way `bin/dhan/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The `SEGMENT:SECURITY_ID` tokens to subscribe to.
            names (dict): Tokens to instrument names.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = script.DhanSession(context.logger)
        socket = script.QuotesSocket('socket_0', tokens, names, session, context.redis, context.logger)
        context.use_instant_waits(socket)
        return socket

    def build_order_socket(self, context):
        """Builds an order updates socket the way `bin/dhan/orders/websocket_order_details` does.

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
        """Every Dhan scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        refused_frame = b'\x32\x0a\x00\x01\x00\x00\x00\x00\x27\x03'
        return [
            (
                'dhan.quotes.every_packet_shape',
                [
                    [
                        ('open',),
                        ('message', self.every_packet_shape_message()),
                        ('message', self.packets.full(COMMODITY_SEGMENT, CRUDE_FUTURE, 6123.0, 0.0)),
                        ('message', self.packets.header(7, 12, EQUITY_SEGMENT, HDFC_BANK) + b'\x00\x00\x00\x00'),
                        ('message', self.packets.header(TICKER, 0, EQUITY_SEGMENT, HDFC_BANK) + b'\x00' * 8),
                        ('message', 'a text frame'),
                        ('message', self.packets.disconnect(805)),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'dhan.quotes.subscribes_a_hundred_a_message',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_many_quotes,
            ),
            (
                'dhan.quotes.authentication_disconnect_logs_in_again',
                [
                    [
                        ('open',),
                        ('message', self.packets.disconnect(807)),
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
                'dhan.quotes.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', self.packets.disconnect(808)),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'dhan.quotes.refused_again_logs_in_again',
                [
                    [
                        ('open',),
                        ('message', self.packets.disconnect(807)),
                    ],
                    [
                        ('open',),
                        ('message', self.packets.disconnect(809)),
                    ],
                    [
                        ('open',),
                        ('message', self.packets.disconnect(808)),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'dhan.quotes.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_quotes,
            ),
            (
                'dhan.quotes.login_again_fails',
                [
                    [
                        ('open',),
                        ('message', self.packets.disconnect(807)),
                    ],
                ],
                {
                    2,
                },
                self.run_quotes,
            ),
            (
                'dhan.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes,
            ),
            (
                'dhan.orders.updates',
                [
                    [
                        ('open',),
                        ('message', json.dumps({'Type': 'order_alert', 'Data': self.dhan_order('5226092501', 'TRADED')})),
                        ('message', json.dumps(self.mixed_messages())),
                        ('message', 'not json'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'dhan.orders.binary_refusal_logs_in_again',
                [
                    [
                        ('open',),
                        ('message', refused_frame),
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
                'dhan.orders.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', refused_frame),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'dhan.orders.refused_again_gives_up',
                [
                    [
                        ('open',),
                        ('message', refused_frame),
                    ],
                    [
                        ('open',),
                        ('message', refused_frame),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'dhan.orders.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_orders,
            ),
            (
                'dhan.orders.login_again_fails',
                [
                    [
                        ('open',),
                        ('message', refused_frame),
                    ],
                ],
                {
                    2,
                },
                self.run_orders,
            ),
            (
                'dhan.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders,
            ),
        ]

    def run_quotes(self, context):
        """Builds a quotes socket for four instruments, two of them named, and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        tokens = [
            'IDX_I:13',
            'MCX_COMM:426016',
            'NSE_EQ:1333',
            'NSE_FNO:35001',
        ]
        names = {
            'NSE_EQ:1333': 'NSE:HDFC Bank',
            'IDX_I:13': 'NSE:Nifty 50',
        }
        return self.run_quotes_for(context, tokens, names)

    def run_many_quotes(self, context):
        """Builds a quotes socket for 205 instruments, which Dhan takes a hundred a message.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        tokens = []
        for security_id in range(1000, 1205):
            tokens.append(f'NSE_EQ:{security_id}')
        return self.run_quotes_for(context, tokens, {})

    def run_quotes_for(self, context, tokens, names):
        """Builds a quotes socket and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The tokens to subscribe to.
            names (dict): Tokens to instrument names.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
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
        harness.StubBrokerAPI.logins.replace_elsewhere('token-from-another-process')

    def every_packet_shape_message(self):
        """One message holding every packet shape, including the single-value packets that are remembered.

        Returns:
            bytes: The message.
        """
        return (
            self.packets.previous_close(EQUITY_SEGMENT, HDFC_BANK, 1650.25)
            + self.packets.quote(EQUITY_SEGMENT, HDFC_BANK, 1660.5, 1655.0)
            + self.packets.open_interest(FUTURES_SEGMENT, NIFTY_FUTURE, 1234500)
            + self.packets.quote(FUTURES_SEGMENT, NIFTY_FUTURE, 25150.5, 25100.0)
            + self.packets.ticker(INDEX_SEGMENT, NIFTY, 25123.45, 1790331329)
            + self.packets.ticker(INDEX_SEGMENT, NIFTY, 25124.0, 0)
            + self.packets.full(EQUITY_SEGMENT, HDFC_BANK, 1661.0, 1655.0)
        )

    def dhan_order(self, order_number, status):
        """An order as Dhan sends it in an `order_alert` message's `Data`.

        Args:
            order_number (str): The order number.
            status (str): Dhan's status.

        Returns:
            dict: The order.
        """
        return {
            'OrderNo': order_number,
            'ExchOrderNo': '1100000012345678',
            'Status': status,
            'ReasonDescription': 'CONFIRMED',
            'Exchange': 'NSE',
            'Segment': 'E',
            'SecurityId': '1333',
            'Symbol': 'HDFCBANK',
            'DisplayName': 'HDFC Bank',
            'TxnType': 'B',
            'Product': 'C',
            'OrderType': 'LMT',
            'Validity': 'DAY',
            'Quantity': 10,
            'TradedQty': 4,
            'Price': 1660.5,
            'TriggerPrice': 0,
            'AvgTradedPrice': 1660.4,
            'OrderDateTime': '2026-09-25 10:15:29',
            'ExchOrderTime': '2026-09-25 10:15:29',
            'CorrelationId': 'ubi',
        }

    def mixed_messages(self):
        """A list payload holding two alerts, an alert without an order number, another type and a non-dictionary.

        Returns:
            list: The payload.
        """
        without_number = self.dhan_order('', 'PENDING')
        return [
            {
                'Type': 'order_alert',
                'Data': self.dhan_order('5226092502', 'PENDING'),
            },
            {
                'Type': 'order_alert',
                'Data': without_number,
            },
            {
                'Type': 'heartbeat',
                'Data': {},
            },
            {
                'Type': 'order_alert',
                'Data': self.dhan_order('5226092503', 'REJECTED'),
            },
            'not a dictionary',
        ]
