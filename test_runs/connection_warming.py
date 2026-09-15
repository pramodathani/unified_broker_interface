"""Offline checks that connection warming and the idle limit never make an order fail.

A local HTTP server on 127.0.0.1 stands in for a broker. It answers orders normally, and it can answer warming pings by resetting the connection, closing it silently straight after answering or 30 milliseconds later, closing it after announcing so, answering with an error, setting a cookie, or answering too slowly. It can also drop a request that arrives on a connection idle longer than a limit without answering, the way a broker's server behaves when it has already timed the connection out.

The checks send orders through a `BrokerOrders` subclass pointed at that server, with and without a warmer running, and require every order to be accepted.
Nothing leaves the machine, and no Redis, database or credentials are used.

Typical usage:

    python -m test_runs.connection_warming
"""

import http.server
import json
import logging
import socket
import struct
import sys
import threading
import time

from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints import orders as orders_blueprint
from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.connection_warmer import (
    ConnectionWarmer,
)
from utilities.configurations import api_configuration


class LocalBrokerState:
    """What the local broker server does and what it has seen.

    Attributes:
        lock (threading.Lock): Guards the counters and lists.
        ping_mode (str): How pings are answered: `normal`, `reset`, `silent_close`, `late_close`, `connection_close`, `error`, `cookie` or `slow`.
        late_close_seconds (float): How long after answering a `late_close` ping the server closes the connection.
        slow_ping_seconds (float): How long a `slow` ping waits before answering.
        idle_abort_seconds (float | None): A request arriving on a connection idle longer than this is dropped without an answer, or None to answer everything.
        connections_opened (int): How many connections the server has accepted.
        pings (int): How many pings arrived.
        orders (list): For each order, a dictionary with `connection_age_seconds` and `had_cookie`.
        aborted_requests (int): How many requests were dropped for arriving on an idle connection.
    """

    def __init__(self):
        """Builds the state for a server that answers everything normally.

        Returns:
            None: This method returns nothing.
        """
        self.lock = threading.Lock()
        self.ping_mode = 'normal'
        self.slow_ping_seconds = 0.5
        self.late_close_seconds = 0.03
        self.idle_abort_seconds = None
        self.connections_opened = 0
        self.pings = 0
        self.orders = []
        self.aborted_requests = 0


class LocalBrokerHandler(http.server.BaseHTTPRequestHandler):
    """One connection to the local broker server, kept alive across requests.

    Attributes:
        protocol_version (str): `HTTP/1.1`, so connections are kept alive.
        opened_at (float): `time.monotonic()` when the connection was accepted.
        last_answer_at (float | None): `time.monotonic()` when the latest answer on this connection was sent.
    """

    protocol_version = 'HTTP/1.1'

    def setup(self):
        """Accepts the connection and counts it.

        Returns:
            None: This method returns nothing.
        """
        super().setup()
        self.opened_at = time.monotonic()
        self.last_answer_at = None
        with self.server.state.lock:
            self.server.state.connections_opened += 1

    def log_message(self, format, *args):
        """Keeps the server quiet.

        Args:
            format (str): The message format.
            *args (object): The message values.

        Returns:
            None: This method returns nothing.
        """
        del format
        del args

    def handle_one_request(self):
        """Reads one request, drops it when the connection had been idle too long, and answers it otherwise.

        Returns:
            None: This method returns nothing.
        """
        self.raw_requestline = self.rfile.readline(65537)
        if not self.raw_requestline:
            self.close_connection = True
            return
        state = self.server.state
        if self.last_answer_at is not None and state.idle_abort_seconds is not None:
            idle_seconds = time.monotonic() - self.last_answer_at
            if idle_seconds > state.idle_abort_seconds:
                with state.lock:
                    state.aborted_requests += 1
                self.close_connection = True
                return
        if not self.parse_request():
            return
        if self.command == 'HEAD':
            self.answer_ping()
        elif self.command == 'POST':
            self.answer_order()
        else:
            self.send_error(405)
        self.wfile.flush()
        self.last_answer_at = time.monotonic()

    def answer_ping(self):
        """Answers a warming ping the way the server's `ping_mode` says.

        Returns:
            None: This method returns nothing.
        """
        state = self.server.state
        with state.lock:
            state.pings += 1
            ping_mode = state.ping_mode
        if ping_mode == 'reset':
            self.connection.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_LINGER,
                struct.pack('ii', 1, 0),
            )
            self.close_connection = True
            return
        if ping_mode == 'slow':
            time.sleep(state.slow_ping_seconds)
        status = 200
        if ping_mode == 'error':
            status = 500
        self.send_response(status)
        self.send_header('Content-Length', '0')
        if ping_mode == 'cookie':
            self.send_header('Set-Cookie', 'warmed=yes; Path=/')
        if ping_mode == 'connection_close':
            self.send_header('Connection', 'close')
            self.close_connection = True
        self.end_headers()
        if ping_mode == 'silent_close':
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
        if ping_mode == 'late_close':
            self.wfile.flush()
            time.sleep(state.late_close_seconds)
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True

    def answer_order(self):
        """Answers an order with an order id, noting the connection's age and whether a cookie came with it.

        Returns:
            None: This method returns nothing.
        """
        length = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(length)
        state = self.server.state
        with state.lock:
            state.orders.append({
                'connection_age_seconds': time.monotonic() - self.opened_at,
                'had_cookie': self.headers.get('Cookie') is not None,
            })
            order_number = len(state.orders)
        body = json.dumps({
            'order_id': f'LOCAL{order_number}',
        }).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LocalBrokerServer(http.server.ThreadingHTTPServer):
    """The local broker server, on a free port of 127.0.0.1.

    Attributes:
        daemon_threads (bool): True, so connection threads never keep the process alive.
        state (LocalBrokerState): What the server does and has seen.
        serving_thread (threading.Thread): The thread serving requests.
    """

    daemon_threads = True

    def __init__(self):
        """Builds and starts the server.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(('127.0.0.1', 0), LocalBrokerHandler)
        self.state = LocalBrokerState()
        self.serving_thread = threading.Thread(
            target=self.serve_forever,
            daemon=True,
        )
        self.serving_thread.start()

    def url(self):
        """The server's base URL.

        Returns:
            str: The URL, ending in a slash.
        """
        return f'http://127.0.0.1:{self.server_address[1]}/'

    def stop(self):
        """Stops the server.

        Returns:
            None: This method returns nothing.
        """
        self.shutdown()
        self.server_close()


class LocalBrokerOrders(BrokerOrders):
    """A broker whose orders go to the local broker server."""

    BROKER_NAME = 'local'
    WARM_TIMEOUT_SECONDS = (
        0.5,
        0.2,
    )
    WARM_SETTLE_SECONDS = 0.05

    def __init__(self, server, maximum_idle_seconds, warm_interval_seconds):
        """Builds the broker against a server.

        Args:
            server (LocalBrokerServer): The server.
            maximum_idle_seconds (float | None): How long a pooled connection may sit idle and still carry a request, or None for no limit.
            warm_interval_seconds (float): How often a warmer pings.

        Returns:
            None: This method returns nothing.
        """
        self.MAXIMUM_IDLE_SECONDS = maximum_idle_seconds
        self.WARM_INTERVAL_SECONDS = warm_interval_seconds
        self.WARM_URL = server.url()
        self.server = server
        super().__init__()

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds a `POST /order` to the local server.

        Args:
            order (object): Unused.
            instrument (object): Unused.
            handle (object): Unused.
            login (object): Unused.
            settings (object): Unused.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'POST',
            self.server.url() + 'order',
            {},
            json_body={
                'quantity': 1,
            },
        )

    def read_order_id(self, response_fields):
        """Reads `order_id`.

        Args:
            response_fields (dict): The server's JSON body.

        Returns:
            object: The order id, or None.
        """
        return response_fields.get('order_id')

    def place(self):
        """Sends one order.

        Returns:
            BrokerAnswer: The answer.
        """
        request = self.build_place_request(None, None, None, None, None)
        return self.send_place(request)


class FailingBrokerOrders(LocalBrokerOrders):
    """A broker whose warming raises an unexpected exception."""

    def warm_connection(self):
        """Raises, as a bug in a broker's warming would.

        Returns:
            str: Never returns.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError('a bug in warming')


class ConnectionWarmingSuite:
    """Runs every check and reports how many passed.

    Attributes:
        logger (logging.Logger): The logger handed to warmers, kept quiet.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    PING_MODES = [
        'normal',
        'reset',
        'silent_close',
        'late_close',
        'connection_close',
        'error',
        'cookie',
        'slow',
    ]

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('connection_warming_suite')
        self.logger.setLevel(logging.CRITICAL)
        self.passed = 0
        self.failed = []

    def check(self, name, condition, detail):
        """Records one check.

        Args:
            name (str): The check's name.
            condition (bool): Whether it passed.
            detail (str): What was observed.

        Returns:
            None: This method returns nothing.
        """
        if condition:
            self.passed = self.passed + 1
            print(f'ok      {name}: {detail}')
        else:
            self.failed.append(name)
            print(f'FAILED  {name}: {detail}')

    def wait_for_pings(self, server, count):
        """Waits until the server has seen a number of pings.

        Args:
            server (LocalBrokerServer): The server.
            count (int): The number of pings to wait for.

        Returns:
            None: This method returns nothing.
        """
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with server.state.lock:
                if server.state.pings >= count:
                    return
            time.sleep(0.01)

    def check_connection_is_reused(self):
        """Orders close together share one connection.

        Returns:
            None: This method returns nothing.
        """
        server = LocalBrokerServer()
        broker = LocalBrokerOrders(server, 30.0, 1.0)
        outcomes = []
        for attempt in range(3):
            outcomes.append(broker.place().outcome)
        server.stop()
        self.check(
            'orders close together reuse one connection',
            (
                outcomes.count('accepted') == 3
                and server.state.connections_opened == 1
            ),
            f'outcomes {outcomes}, connections opened {server.state.connections_opened}',
        )

    def check_idle_connection_is_the_risk(self):
        """Without the idle limit, a connection the server has timed out makes the next order unknown; this is the failure the limit prevents.

        Returns:
            None: This method returns nothing.
        """
        server = LocalBrokerServer()
        server.state.idle_abort_seconds = 0.3
        broker = LocalBrokerOrders(server, None, 1.0)
        first = broker.place().outcome
        time.sleep(0.5)
        second = broker.place()
        server.stop()
        self.check(
            'without the idle limit a timed-out connection fails the order',
            first == 'accepted' and second.outcome == 'unknown',
            f'first {first}, second {second.outcome} ({second.status_message})',
        )

    def check_idle_limit_prevents_it(self):
        """With the idle limit below the server's timeout, the next order opens a new connection and is accepted.

        Returns:
            None: This method returns nothing.
        """
        server = LocalBrokerServer()
        server.state.idle_abort_seconds = 0.3
        broker = LocalBrokerOrders(server, 0.2, 1.0)
        first = broker.place().outcome
        time.sleep(0.5)
        second = broker.place().outcome
        server.stop()
        self.check(
            'the idle limit opens a new connection instead',
            (
                first == 'accepted'
                and second == 'accepted'
                and server.state.connections_opened == 2
                and server.state.aborted_requests == 0
            ),
            f'first {first}, second {second}, connections opened {server.state.connections_opened}, dropped requests {server.state.aborted_requests}',
        )

    def check_warmer_keeps_the_connection_warm(self):
        """With a warmer pinging more often than the idle limit, an order after a long pause reuses the first order's connection.

        Returns:
            None: This method returns nothing.
        """
        server = LocalBrokerServer()
        server.state.idle_abort_seconds = 0.6
        broker = LocalBrokerOrders(server, 0.4, 0.1)
        first = broker.place().outcome
        warmer = ConnectionWarmer(broker, self.logger)
        warmer.start()
        time.sleep(1.5)
        with server.state.lock:
            pings_so_far = server.state.pings
        self.wait_for_pings(server, pings_so_far + 1)
        time.sleep(broker.WARM_SETTLE_SECONDS + 0.02)
        second = broker.place().outcome
        warmer.stop()
        server.stop()
        second_age = server.state.orders[-1]['connection_age_seconds']
        self.check(
            'a warmed connection carries an order after a pause',
            (
                first == 'accepted'
                and second == 'accepted'
                and second_age >= 1.5
                and server.state.aborted_requests == 0
            ),
            f'first {first}, second {second}, second order connection age {second_age:.2f} s, pings {server.state.pings}, connections opened {server.state.connections_opened}',
        )

    def check_warm_connection_outcomes(self):
        """A ping keeps a healthy connection and discards one the server closes, and the next order is accepted either way.

        Returns:
            None: This method returns nothing.
        """
        for ping_mode, expected in (
            ('normal', 'kept'),
            ('silent_close', 'discarded'),
            ('connection_close', 'discarded'),
        ):
            server = LocalBrokerServer()
            server.state.ping_mode = ping_mode
            broker = LocalBrokerOrders(server, 30.0, 1.0)
            warm_result = broker.warm_connection()
            order = broker.place().outcome
            server.stop()
            self.check(
                f'a {ping_mode} ping is {expected} and the next order is accepted',
                warm_result == expected and order == 'accepted',
                f'ping {warm_result}, order {order}, connections opened {server.state.connections_opened}',
            )

    def check_late_close_is_caught_by_the_settle_check(self):
        """An order sent straight after a ping whose connection the server closes a moment later is accepted, because the ping watched the connection before returning it.

        Without the settle check the ping would return the connection at once, the order would be written to it before the server's close arrived, and the order would be answered `unknown`.

        Returns:
            None: This method returns nothing.
        """
        results = []
        for attempt in range(20):
            server = LocalBrokerServer()
            server.state.ping_mode = 'late_close'
            broker = LocalBrokerOrders(server, 30.0, 1.0)
            warm_result = broker.warm_connection()
            order = broker.place().outcome
            server.stop()
            results.append((warm_result, order))
        good = results.count(('discarded', 'accepted'))
        self.check(
            'an order straight after a late-closing ping is accepted',
            good == len(results),
            f'{good} of {len(results)} pings discarded with the next order accepted, results {sorted(set(results))}',
        )

    def check_ping_cookie_never_reaches_an_order(self):
        """A cookie set on a ping's answer is not sent with a later order.

        Returns:
            None: This method returns nothing.
        """
        server = LocalBrokerServer()
        server.state.ping_mode = 'cookie'
        broker = LocalBrokerOrders(server, 30.0, 1.0)
        broker.warm_connection()
        order = broker.place().outcome
        server.stop()
        had_cookie = server.state.orders[-1]['had_cookie']
        self.check(
            "a ping's cookie is not sent with an order",
            (
                order == 'accepted'
                and not had_cookie
                and len(broker.session.cookies) == 0
            ),
            f'order {order}, cookie sent {had_cookie}, session cookies {len(broker.session.cookies)}',
        )

    def send_orders_in_threads(self, broker, thread_count, orders_per_thread):
        """Sends orders from several threads at once.

        Args:
            broker (LocalBrokerOrders): The broker.
            thread_count (int): How many threads.
            orders_per_thread (int): How many orders each thread sends.

        Returns:
            list: Every order's outcome.
        """
        outcomes = []
        outcomes_lock = threading.Lock()

        def send_orders():
            """Sends this thread's orders, recording each outcome.

            Returns:
                None: This function returns nothing.
            """
            for order_number in range(orders_per_thread):
                answer = broker.place()
                with outcomes_lock:
                    outcomes.append(answer.outcome)
                time.sleep(0.003 * (order_number % 5))

        threads = []
        for thread_number in range(thread_count):
            thread = threading.Thread(target=send_orders)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        return outcomes

    def check_hostile_pings_never_fail_orders(self):
        """Orders sent from four threads while a warmer pings every few milliseconds are all accepted, however the server answers the pings.

        Returns:
            None: This method returns nothing.
        """
        for ping_mode in self.PING_MODES:
            server = LocalBrokerServer()
            server.state.ping_mode = ping_mode
            server.state.slow_ping_seconds = 0.3
            broker = LocalBrokerOrders(server, 5.0, 0.005)
            warmer = ConnectionWarmer(broker, self.logger)
            warmer.start()
            outcomes = self.send_orders_in_threads(broker, 4, 50)
            still_running = warmer.is_running()
            warmer.stop()
            server.stop()
            accepted = outcomes.count('accepted')
            cookies = 0
            for order in server.state.orders:
                if order['had_cookie']:
                    cookies = cookies + 1
            self.check(
                f'{ping_mode} pings never fail an order',
                (
                    accepted == len(outcomes)
                    and cookies == 0
                    and still_running
                    and warmer.pings > 0
                ),
                f'{accepted} of {len(outcomes)} orders accepted, {warmer.pings} pings ({warmer.failures} raised), orders with a cookie {cookies}, warmer running {still_running}',
            )

    def check_warmer_survives_a_bug(self):
        """A warmer whose broker's warming raises keeps running and keeps trying.

        Returns:
            None: This method returns nothing.
        """
        server = LocalBrokerServer()
        broker = FailingBrokerOrders(server, 30.0, 0.01)
        warmer = ConnectionWarmer(broker, self.logger)
        warmer.start()
        time.sleep(0.3)
        still_running = warmer.is_running()
        order = broker.place().outcome
        warmer.stop()
        server.stop()
        self.check(
            'a warmer keeps running when warming raises',
            (
                still_running
                and warmer.failures > 5
                and warmer.failures == warmer.pings
                and order == 'accepted'
            ),
            f'running {still_running}, pings {warmer.pings}, raised {warmer.failures}, order {order}',
        )

    def fake_cache(self):
        """Hands the blueprint no Redis client, since building it reads none.

        Returns:
            None: Always None.
        """
        return None

    def check_blueprint_warming_configuration(self):
        """Blueprints start no warmer without configuration, and ignore names that are not brokers instead of failing to start.

        Returns:
            None: This method returns nothing.
        """
        original_get_cache = blueprint_base.get_cache
        original_get_mongo_database = blueprint_base.get_mongo_db
        original_warm_brokers = api_configuration['order_warm_brokers']
        blueprint_base.get_cache = self.fake_cache
        blueprint_base.get_mongo_db = self.fake_cache
        try:
            api_configuration['order_warm_brokers'] = [
                '',
            ]
            unconfigured = orders_blueprint.OrdersBlueprint()
            api_configuration['order_warm_brokers'] = [
                'upstox',
                '',
                'not-a-broker',
            ]
            misconfigured = orders_blueprint.OrdersBlueprint()
        finally:
            blueprint_base.get_cache = original_get_cache
            blueprint_base.get_mongo_db = original_get_mongo_database
            api_configuration['order_warm_brokers'] = original_warm_brokers
        self.check(
            'no warmer starts without configuration or for unknown names',
            (
                unconfigured.connection_warmers == []
                and misconfigured.connection_warmers == []
            ),
            f'warmers without configuration {len(unconfigured.connection_warmers)}, with unknown names {len(misconfigured.connection_warmers)}',
        )

    def run(self):
        """Runs every check.

        Returns:
            int: The exit code: 0 when every check passed, 1 otherwise.
        """
        logging.getLogger('rest_api.orders').setLevel(logging.CRITICAL)
        self.check_connection_is_reused()
        self.check_idle_connection_is_the_risk()
        self.check_idle_limit_prevents_it()
        self.check_warmer_keeps_the_connection_warm()
        self.check_warm_connection_outcomes()
        self.check_late_close_is_caught_by_the_settle_check()
        self.check_ping_cookie_never_reaches_an_order()
        self.check_hostile_pings_never_fail_orders()
        self.check_warmer_survives_a_bug()
        self.check_blueprint_warming_configuration()
        total = self.passed + len(self.failed)
        print(f'{self.passed}/{total} checks passed.')
        if self.failed:
            return 1
        return 0


if __name__ == '__main__':
    sys.exit(ConnectionWarmingSuite().run())
