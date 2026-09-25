"""The INDmoney quotes and order updates sockets, driven through scripted INDstocks connections."""

import json
import types

from stock_brokers.websockets import indmoney as indmoney_websockets
from test_runs.websocket_feeds import harness

QUOTES_SCRIPT = 'bin/indmoney/instruments/websocket_quotes'
ORDERS_SCRIPT = 'bin/indmoney/orders/websocket_order_details'

FEED_MILLISECONDS = 1790316329123


class StubIndmoneyAPI(harness.StubBrokerAPI):
    """A stand-in for `INDMoneyAPI`.

    Attributes:
        SETTINGS (dict): The client id the sockets send as `x-api-key`, reset before every scenario.
    """

    SETTINGS = {
        'client_id': 'ind-api-key',
    }


class IndmoneyFeedCases:
    """Every INDmoney scenario, and how each socket is built the way its script builds it.

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
        """The modules replaced while an INDmoney scenario runs.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Module names to stand-ins.
        """
        harness.StubBrokerAPI.logins = context.logins
        StubIndmoneyAPI.SETTINGS = {
            'client_id': 'ind-api-key',
        }
        api_module = types.ModuleType('stock_brokers.api.indmoney')
        api_module.INDMoneyAPI = StubIndmoneyAPI
        return {
            'stock_brokers.api.indmoney': api_module,
        }

    def datetime_holders(self):
        """The modules whose `datetime` name is frozen while a scenario runs.

        Returns:
            list: The modules.
        """
        return [
            self.loader.load(ORDERS_SCRIPT),
            indmoney_websockets,
        ]

    def build_quotes_socket(self, context, tokens, names):
        """Builds a quotes socket the way `bin/indmoney/instruments/websocket_quotes` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.
            tokens (list): The `SEGMENT:TOKEN` tokens to subscribe to, all of one segment.
            names (dict): Tokens to instrument names.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(QUOTES_SCRIPT)
        session = indmoney_websockets.IndmoneySession(context.logger)
        store = script.IndmoneyQuotesStore(context.redis)
        socket = indmoney_websockets.IndmoneyQuotesSocket(
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
        """Builds an order updates socket the way `bin/indmoney/orders/websocket_order_details` does.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            object: The socket, with instant waits.
        """
        script = self.loader.load(ORDERS_SCRIPT)
        session = indmoney_websockets.IndmoneySession(context.logger)
        store = script.IndmoneyOrderUpdatesStore(context.redis, context.logger)
        socket = indmoney_websockets.IndmoneyOrderUpdatesSocket(session, store.write_updates, context.logger)
        context.use_instant_waits(socket)
        return socket

    def scenarios(self):
        """Every INDmoney scenario, in the order they are recorded.

        Returns:
            list: Tuples of the scenario's name, its scripted connections, its failing logins and the method that runs it.
        """
        refused = harness.FakeWebsocketError('Handshake status 513 Unknown', status_code=513)
        other_error = harness.FakeWebsocketError('Connection reset by peer')
        return [
            (
                'indmoney.quotes.every_message_shape',
                [
                    [
                        ('open',),
                        ('message', self.double_encoded_frame()),
                        ('message', json.dumps([self.update('11536', {'ltp': 1650.5}, FEED_MILLISECONDS), 'not a dictionary'])),
                        ('message', json.dumps(self.update('NSE:2885', {'ltp': 2951.0, 'volume': '1200100.0'}, 1790316330))),
                        ('message', json.dumps(self.update('99999', {'ltp': 10.0}, None)).encode('utf-8')),
                        ('message', json.dumps({'instrument': '2885', 'timestamp': FEED_MILLISECONDS})),
                        ('message', json.dumps(self.update('2885', {'volume': 5}, FEED_MILLISECONDS))),
                        ('message', 'not json\n\n'),
                        ('message', 12345),
                        ('error', other_error),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_quotes,
            ),
            (
                'indmoney.quotes.without_client_id',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_quotes_without_client_id,
            ),
            (
                'indmoney.quotes.refused_then_logs_in_again',
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
                'indmoney.quotes.token_replaced_elsewhere',
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
                'indmoney.quotes.refused_again_gives_up',
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
                'indmoney.quotes.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_quotes,
            ),
            (
                'indmoney.quotes.login_again_fails',
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
                'indmoney.quotes.first_login_fails',
                [],
                {
                    1,
                },
                self.run_quotes,
            ),
            (
                'indmoney.orders.updates',
                [
                    [
                        ('open',),
                        ('message', json.dumps({'status': 'subscribed'})),
                        ('message', json.dumps({'action': 'subscribe', 'mode': 'order_update'})),
                        ('message', json.dumps({'type': 'order', 'data': self.indstocks_order('IND2609250001', 'COMPLETE')})),
                        ('message', json.dumps(self.mixed_messages())),
                        ('message', json.dumps(self.indstocks_order('IND2609250004', 'CANCELLED') | {'type': 'order'}).encode('utf-8')),
                        ('message', 'not json'),
                        ('error', other_error),
                        ('close', 1000, 'normal closure'),
                    ],
                ],
                set(),
                self.run_orders,
            ),
            (
                'indmoney.orders.without_client_id',
                [
                    [
                        ('open',),
                    ],
                ],
                set(),
                self.run_orders_without_client_id,
            ),
            (
                'indmoney.orders.refused_then_logs_in_again',
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
                'indmoney.orders.token_replaced_elsewhere',
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
                'indmoney.orders.refused_again_gives_up',
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
                'indmoney.orders.failed_connects_give_up',
                harness.ConnectionPlan.failed_connects(12),
                set(),
                self.run_orders,
            ),
            (
                'indmoney.orders.login_again_fails',
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
                'indmoney.orders.first_login_fails',
                [],
                {
                    1,
                },
                self.run_orders,
            ),
        ]

    def update(self, instrument, data, timestamp):
        """One INDstocks price update.

        Args:
            instrument (str): The instrument as the feed names it, usually a bare security id.
            data (dict): The update's `data` fields.
            timestamp (int | None): The update's timestamp, in milliseconds or seconds.

        Returns:
            dict: The update.
        """
        update = {
            'mode': 'full',
            'instrument': instrument,
            'data': data,
        }
        if timestamp is not None:
            update['timestamp'] = timestamp
        return update

    def double_encoded_frame(self):
        """A frame of two lines, each a JSON string whose content is itself JSON, as INDstocks sends updates.

        Returns:
            str: The frame.
        """
        first = self.update('2885', {'ltp': 2950.5, 'open': 2935, 'high': 2960, 'low': 2925, 'close': 2950.5, 'volume': 1200000.0, 'total_buy_qty': 5400, 'total_sell_qty': 6100, 'oi': '', 'ltt': FEED_MILLISECONDS - 1000, 'bid_price': 2950.4, 'ask_price': 2950.6}, FEED_MILLISECONDS)
        second = self.update('11536', {'ltp': 'unreadable', 'open': 1640}, FEED_MILLISECONDS)
        return json.dumps(json.dumps(first)) + '\n' + json.dumps(json.dumps(second)) + '\n'

    def run_quotes(self, context):
        """Builds a quotes socket for two NSE instruments, one named, and runs its reconnect loop.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up, or the error that stopped it being built.
        """
        tokens = [
            'NSE:11536',
            'NSE:2885',
        ]
        names = {
            'NSE:2885': 'NSE:RELIANCE',
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

    def run_quotes_without_client_id(self, context):
        """Runs a quotes socket whose settings hold no client id, so no `x-api-key` header is sent.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        StubIndmoneyAPI.SETTINGS = {
            'client_id': '',
        }
        return self.run_quotes(context)

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

    def run_orders_without_client_id(self, context):
        """Runs an order socket whose settings hold no client id, so no `x-api-key` header is sent.

        Args:
            context (harness.ScenarioContext): The scenario being run.

        Returns:
            dict: Whether the socket gave up.
        """
        StubIndmoneyAPI.SETTINGS = {
            'client_id': None,
        }
        return self.run_orders(context)

    def log_in_elsewhere(self):
        """Replaces the token as another process logging in would.

        Returns:
            None: This method returns nothing.
        """
        harness.StubBrokerAPI.logins.replace_elsewhere('token-from-another-process')

    def indstocks_order(self, order_id, status):
        """An order as INDstocks sends it in an order update's `data`.

        Args:
            order_id (str): The order id.
            status (str): INDstocks' status.

        Returns:
            dict: The order.
        """
        return {
            'order_id': order_id,
            'exchange_order_id': '1100000012345678',
            'status': status,
            'status_message': '',
            'exchange': 'NSE',
            'segment': 'EQUITY',
            'security_id': '2885',
            'trading_symbol': 'RELIANCE',
            'txn_type': 'BUY',
            'product': 'CNC',
            'order_type': 'LIMIT',
            'validity': 'DAY',
            'qty': 10,
            'traded_qty': 4,
            'limit_price': 2950.5,
            'trigger_price': 0,
            'avg_traded_price': 2950.4,
            'created_at': '2026-09-25T10:15:29',
            'updated_at': '2026-09-25T10:15:30',
        }

    def mixed_messages(self):
        """A list payload holding two orders, an order without an id, a heartbeat and a non-dictionary.

        Returns:
            list: The payload.
        """
        without_id = self.indstocks_order('', 'OPEN')
        return [
            {
                'type': 'order',
                'data': self.indstocks_order('IND2609250002', 'OPEN'),
            },
            {
                'type': 'order',
                'data': without_id,
            },
            {
                'type': 'heartbeat',
            },
            {
                'type': 'order',
                'data': self.indstocks_order('IND2609250003', 'REJECTED'),
            },
            'not a dictionary',
        ]
