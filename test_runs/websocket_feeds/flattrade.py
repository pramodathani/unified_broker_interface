"""The Flattrade quotes and order updates sockets, driven through scripted Noren connections."""

import json
import types

from stock_brokers.websockets import flattrade as flattrade_websockets
from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/flattrade/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/flattrade/orders/websocket_order_details'

FEED_TIME = 1790316329
JUST_AFTER_MIDNIGHT = 1790274610


class StubFlattradeAPI(harness.StubBrokerAPI):
    """A stand-in for `FlattradeAPI`, whose `post` answers the UserDetails check the sockets confirm a login with.

    Attributes:
        SETTINGS (dict): The user id the sockets authenticate as.
        refused_confirmations (set): The login numbers whose session UserDetails refuses.
    """

    SETTINGS = {
        'username': 'FT012345',
    }
    refused_confirmations = set()

    def post(self, url, timeout=None):
        """Answers UserDetails for the login in force, refusing it when the scenario says so.

        Args:
            url (str): The endpoint.
            timeout (float | None): The request timeout.

        Returns:
            dict: The response, as `BrokerAPI.post` returns it.
        """
        ledger = harness.StubBrokerAPI.logins
        ledger.event_log.add('post', url, timeout)
        if ledger.login_count in StubFlattradeAPI.refused_confirmations:
            return {
                'data': {
                    'stat': 'Not_Ok',
                    'emsg': 'Session Expired :  Invalid Session Key',
                },
            }
        return {
            'data': {
                'stat': 'Ok',
                'uname': 'FLATTRADE USER',
            },
        }


class FlattradeFeedCases:
    """Every Flattrade scenario, and how each socket is built the way its script builds it.

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
        """The modules replaced while a Flattrade scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        StubFlattradeAPI.refused_confirmations = set()
        api_module = types.ModuleType('stock_brokers.api.flattrade')
        api_module.FlattradeAPI = StubFlattradeAPI
        return {
            'stock_brokers.api.flattrade': api_module,
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
            flattrade_websockets,
        ]

    def build_quotes_socket(self, context, tokens, names):
        """Builds a quotes socket the way `bin/flattrade/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The `EXCHANGE|TOKEN` tokens to subscribe to.
            names (dict): Tokens to instrument names, which the socket adds to.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = flattrade_websockets.FlattradeSession(context.logger)
        store = script.FlattradeQuotesStore(context.redis)
        socket = flattrade_websockets.FlattradeQuotesSocket(
            'socket_0',
            tokens,
            names,
            session,
            store.write_names,
            store.write_ticks,
            context.logger,
        )
        context.use_instant_waits(socket)
        return socket

    def build_order_socket(self, context):
        """Builds an order updates socket the way `bin/flattrade/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        store = script.FlattradeOrderUpdatesStore(context.redis, context.logger)
        session = flattrade_websockets.FlattradeSession(context.logger)
        socket = flattrade_websockets.FlattradeOrderUpdatesSocket(session, store.write_updates, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every Flattrade scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        accepted = json.dumps({'t': 'ak', 's': 'OK'})
        refused = json.dumps({'t': 'ak', 's': 'NOT_OK', 'emsg': 'Invalid Session Key'})
        return [
            (
                'flattrade.quotes.every_message_shape',
                [
                    self.every_message_shape_connection(),
                ],
                set(),
                self.run_quotes,
            ),
            (
                'flattrade.quotes.refused_then_logs_in_again',
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
                'flattrade.quotes.token_replaced_elsewhere',
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
                'flattrade.quotes.refused_again_gives_up',
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
                'flattrade.quotes.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_quotes,
            ),
            (
                'flattrade.quotes.login_again_fails',
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
                'flattrade.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes,
            ),
            (
                'flattrade.quotes.confirmation_refused_after_logging_in_again',
                [
                    [
                        ('open',),
                        ('message', refused),
                    ],
                ],
                set(),
                self.run_quotes_with_second_confirmation_refused,
            ),
            (
                'flattrade.orders.first_confirmation_refused',
                [],
                set(),
                self.run_orders_with_first_confirmation_refused,
            ),
            (
                'flattrade.orders.updates',
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
                'flattrade.orders.refused_then_logs_in_again',
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
                'flattrade.orders.token_replaced_elsewhere',
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
                'flattrade.orders.refused_again_gives_up',
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
                'flattrade.orders.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_orders,
            ),
            (
                'flattrade.orders.login_again_fails',
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
                'flattrade.orders.first_login_fails',
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
            'NSE|2885': 'NSE:RELIANCE OLD NAME',
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

    def run_quotes_with_second_confirmation_refused(self, context):
        """Runs a quotes socket whose second login UserDetails refuses to confirm.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        StubFlattradeAPI.refused_confirmations = {
            2,
        }
        return self.run_quotes(context)

    def run_orders_with_first_confirmation_refused(self, context):
        """Builds an order socket whose first login UserDetails refuses to confirm.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: The error that stopped the socket being built.
        """
        StubFlattradeAPI.refused_confirmations = {
            1,
        }
        return self.run_orders(context)

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
