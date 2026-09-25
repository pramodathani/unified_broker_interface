"""The Shoonya quotes and order updates sockets, driven through scripted Noren connections."""

import json
import types

from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/shoonya/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/shoonya/orders/websocket_order_details'

FEED_TIME = 1790316329
JUST_AFTER_MIDNIGHT = 1790274610


class StubShoonyaAPI(harness.StubBrokerAPI):
    """A stand-in for `ShoonyaAPI`.

    Attributes:
        SETTINGS (dict): The UCC code the sockets authenticate as.
    """

    SETTINGS = {
        'ucc_code': 'FA12345',
    }


class ShoonyaFeedCases:
    """Every Shoonya scenario, and how each socket is built the way its script builds it.

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
        """The modules replaced while a Shoonya scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        api_module = types.ModuleType('stock_brokers.api.shoonya')
        api_module.ShoonyaAPI = StubShoonyaAPI
        return {
            'stock_brokers.api.shoonya': api_module,
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
        """Builds a quotes socket the way `bin/shoonya/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The `EXCHANGE|TOKEN` tokens to subscribe to.
            names (dict): Tokens to instrument names, which the socket adds to.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = script.ShoonyaSession(context.logger)
        socket = script.QuotesSocket('socket_0', tokens, names, session, context.redis, context.logger)
        context.use_instant_waits(socket)
        return socket

    def build_order_socket(self, context):
        """Builds an order updates socket the way `bin/shoonya/orders/websocket_order_details` does.

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
        """Every Shoonya scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        accepted = json.dumps({'t': 'ak', 's': 'OK'})
        refused = json.dumps({'t': 'ak', 's': 'NOT_OK', 'emsg': 'Invalid Session Key'})
        return [
            (
                'shoonya.quotes.every_message_shape',
                [
                    self.every_message_shape_connection(),
                ],
                set(),
                self.run_quotes,
            ),
            (
                'shoonya.quotes.refused_then_logs_in_again',
                [
                    [
                        ('open',),
                        ('message', refused),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                        ('message', accepted),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'shoonya.quotes.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', refused),
                    ],
                    [
                        ('open',),
                        ('message', accepted),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'shoonya.quotes.refused_again_gives_up',
                [
                    [
                        ('open',),
                        ('message', refused),
                    ],
                    [
                        ('open',),
                        ('message', refused),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'shoonya.quotes.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_quotes,
            ),
            (
                'shoonya.quotes.login_again_fails',
                [
                    [
                        ('open',),
                        ('message', refused),
                    ],
                ],
                {
                    2,
                },
                self.run_quotes,
            ),
            (
                'shoonya.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes,
            ),
            (
                'shoonya.orders.updates',
                [
                    [
                        ('open',),
                        ('message', accepted),
                        ('message', json.dumps(self.noren_order('26092500000001', 'COMPLETE'))),
                        ('message', json.dumps(self.mixed_messages())),
                        ('message', json.dumps(self.noren_order('26092500000004', 'CANCELED')).encode('utf-8')),
                        ('message', 'not json'),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'shoonya.orders.refused_then_logs_in_again',
                [
                    [
                        ('open',),
                        ('message', refused),
                        ('close', None, None),
                    ],
                    [
                        ('open',),
                        ('message', accepted),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'shoonya.orders.token_replaced_elsewhere',
                [
                    [
                        ('open',),
                        ('call', self.log_in_elsewhere),
                        ('message', refused),
                    ],
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'shoonya.orders.refused_again_gives_up',
                [
                    [
                        ('open',),
                        ('message', refused),
                    ],
                    [
                        ('open',),
                        ('message', refused),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'shoonya.orders.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_orders,
            ),
            (
                'shoonya.orders.login_again_fails',
                [
                    [
                        ('open',),
                        ('message', refused),
                    ],
                ],
                {
                    2,
                },
                self.run_orders,
            ),
            (
                'shoonya.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders,
            ),
        ]

    def every_message_shape_connection(self):
        """One connection carrying every kind of message the quotes decoder handles.

        Returns:
            list: The scripted steps.
        """
        steps = [
            ('open',),
            ('message', json.dumps({'t': 'ak', 's': 'Ok'})),
        ]
        messages = [
            {'t': 'tk', 'e': 'NSE', 'tk': '2885', 'ts': 'RELIANCE-EQ', 'lp': '2950.50', 'c': '2930.00', 'o': '2935.00', 'h': '2960.00', 'l': '2925.00', 'v': '1200000', 'ltq': '25', 'ap': '2948.10', 'tbq': '5400', 'tsq': '6100', 'ltt': str(FEED_TIME - 1), 'ft': str(FEED_TIME)},
            {'t': 'tf', 'e': 'NSE', 'tk': '2885', 'lp': '2951.00', 'ft': str(FEED_TIME + 1)},
            {'t': 'dk', 'e': 'NFO', 'tk': '35001', 'ts': 'NIFTY26OCTFUT', 'lp': '25150.50', 'c': '25100.00', 'oi': '1234500', 'ltt': '25-09-2026 10:15:29', 'ft': str(FEED_TIME), 'bp1': '25150.00', 'bq1': '75', 'bo1': '3', 'sp1': '25151.00', 'sq1': '150', 'so1': '4', 'bp2': '25149.50', 'bq2': '300', 'bo2': '5'},
            {'t': 'df', 'e': 'NFO', 'tk': '35001', 'lp': '25152.00', 'ltt': '10:15:20', 'ft': str(FEED_TIME + 2)},
            {'t': 'tk', 'e': 'MCX', 'tk': '426016', 'ts': 'CRUDEOIL26OCTFUT', 'lp': '6123.00', 'pc': '0.39', 'ltt': '23:59:58', 'ft': str(JUST_AFTER_MIDNIGHT)},
            {'t': 'tk', 'e': 'BSE', 'tk': '500325', 'ts': 'RELIANCE', 'c': '2931.00'},
            {'t': 'tf', 'e': 'BSE', 'tk': '500325', 'lp': 'NA', 'ltt': 'NA'},
            {'t': 'tf', 'e': 'BSE', 'tk': '500325', 'lp': '2951.10', 'ltt': 'soon'},
            {'t': 'tf', 'e': 'NSE', 'lp': '1.00'},
            {'t': 'om', 'e': 'NSE', 'tk': '2885'},
        ]
        for message in messages:
            steps.append(('message', json.dumps(message)))
        steps.append(('message', json.dumps({'t': 'tf', 'e': 'NSE', 'tk': '2885', 'v': '1200100'}).encode('utf-8')))
        steps.append(('message', json.dumps([1, 2])))
        steps.append(('message', 'not json'))
        steps.append(('close', 1000, 'normal closure'))
        return steps

    def run_quotes(self, context):
        """Builds a quotes socket for four instruments, one already named, and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        tokens = [
            'BSE|500325',
            'MCX|426016',
            'NFO|35001',
            'NSE|2885',
        ]
        names = {
            'NFO|35001': 'NFO:NIFTY OCT FUT',
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
            'names': names,
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

    def noren_order(self, order_number, status):
        """An `om` order update as Noren sends it, every value a string.

        Args:
            order_number (str): The Noren order number.
            status (str): Noren's status.

        Returns:
            dict: The message.
        """
        return {
            't': 'om',
            'norenordno': order_number,
            'exchordid': '1100000012345678',
            'status': status,
            'rejreason': '',
            'exch': 'NSE',
            'tsym': 'RELIANCE-EQ',
            'token': '2885',
            'trantype': 'B',
            'prd': 'C',
            'prctyp': 'LMT',
            'ret': 'DAY',
            'qty': '10',
            'fillshares': '4',
            'cancelqty': '0',
            'dscqty': '0',
            'prc': '2950.50',
            'trgprc': '0.00',
            'avgprc': '2950.40',
            'norentm': '10:15:29 25-09-2026',
            'exch_tm': '25-09-2026 10:15:29',
            'remarks': 'ubi',
        }

    def mixed_messages(self):
        """A list payload holding two updates, an update without an order number, another type and a non-dictionary.

        Returns:
            list: The payload.
        """
        without_number = self.noren_order('', 'OPEN')
        return [
            self.noren_order('26092500000002', 'OPEN'),
            without_number,
            {
                't': 'dk',
                'e': 'NSE',
                'tk': '2885',
            },
            self.noren_order('26092500000003', 'REJECTED'),
            'not a dictionary',
        ]
