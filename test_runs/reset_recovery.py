"""Offline checks that a place-order request whose connection is reset is settled from the broker's order book instead of being left unknown.

A local HTTP server on 127.0.0.1 stands in for a Noren broker such as Flattrade. Its `PlaceOrder` can answer normally, reset the connection without recording the order, the way Flattrade did 23 times on 19 and 21 October 2026, or record the order and then reset, the case in which sending again would place it twice. Its `OrderBook` can list the recorded orders, answer Noren's empty-book refusal, refuse with another error, or reset too.

The checks send orders through a `NorenOrders` subclass pointed at that server and look at the outcome, at how many orders the server recorded and at how many times the book was read.
Nothing leaves the machine, and no Redis, database or credentials are used.

Typical usage:

    python -m test_runs.reset_recovery
"""

import datetime
import http.client
import http.server
import json
import socket
import struct
import sys
import threading
import time
import urllib.parse
import zoneinfo

import requests
import urllib3.exceptions

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.noren import NorenOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class LocalNorenState:
    """What the local Noren server does and what it has seen.

    Attributes:
        lock (threading.Lock): Guards everything below.
        place_modes (list): How each coming `PlaceOrder` is answered, first first: `normal`, `reset_before` or `reset_after`; `normal` once the list is empty.
        book_modes (list): How each coming `OrderBook` is answered, first first: `normal`, `error` or `reset`; `normal` once the list is empty.
        orders (list): The `jData` fields of every recorded order, each with `norenordno` and `norentm` added.
        place_requests (int): How many `PlaceOrder` requests arrived.
        book_requests (int): How many `OrderBook` requests arrived.
        book_keys (list): The `jKey` of each `OrderBook` request.
    """

    def __init__(self):
        """Builds the state of a server that answers everything normally.

        Returns:
            None: This method returns nothing.
        """
        self.lock = threading.Lock()
        self.place_modes = []
        self.book_modes = []
        self.orders = []
        self.place_requests = 0
        self.book_requests = 0
        self.book_keys = []

    def record(self, fields, seconds_ago=0.0):
        """Records an order as the broker's book would list it.

        Args:
            fields (dict): The order's `jData` fields.
            seconds_ago (float): How long ago the broker received it.

        Returns:
            str: Its order number.
        """
        moment = datetime.datetime.now(INDIA) - datetime.timedelta(seconds=seconds_ago)
        with self.lock:
            number = f'2610210{len(self.orders) + 1:07d}'
            row = dict(fields)
            row['norenordno'] = number
            row['norentm'] = moment.strftime('%H:%M:%S %d-%m-%Y')
            row['stat'] = 'Ok'
            self.orders.append(row)
        return number


class LocalNorenHandler(http.server.BaseHTTPRequestHandler):
    """One connection to the local Noren server, kept alive across requests.

    Attributes:
        protocol_version (str): `HTTP/1.1`, so connections are kept alive.
    """

    protocol_version = 'HTTP/1.1'

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

    def do_POST(self):
        """Answers `PlaceOrder` and `OrderBook`.

        Returns:
            None: This method returns nothing.
        """
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length).decode()
        form = urllib.parse.parse_qs(body)
        fields = json.loads(form['jData'][0])
        login_token = form.get('jKey', [''])[0]
        if self.path.endswith('/PlaceOrder'):
            self.answer_place(fields)
        elif self.path.endswith('/OrderBook'):
            self.answer_book(login_token)
        else:
            self.answer({'stat': 'Not_Ok', 'emsg': 'unknown path'})

    def next_mode(self, modes):
        """Takes the next answer mode from a list.

        Args:
            modes (list): `place_modes` or `book_modes`.

        Returns:
            str: The mode, `normal` when the list is empty.
        """
        if modes:
            return modes.pop(0)
        return 'normal'

    def reset(self):
        """Resets the connection, so the client reads `Connection reset by peer`.

        Returns:
            None: This method returns nothing.
        """
        self.connection.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_LINGER,
            struct.pack('ii', 1, 0),
        )
        self.close_connection = True

    def answer(self, document):
        """Sends a JSON answer.

        Args:
            document (object): The answer.

        Returns:
            None: This method returns nothing.
        """
        encoded = json.dumps(document).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def answer_place(self, fields):
        """Answers one `PlaceOrder` the way the next place mode says.

        Args:
            fields (dict): The order's `jData` fields.

        Returns:
            None: This method returns nothing.
        """
        state = self.server.state
        with state.lock:
            state.place_requests += 1
            mode = self.next_mode(state.place_modes)
        if mode == 'reset_before':
            self.reset()
            return
        number = state.record(fields)
        if mode == 'reset_after':
            self.reset()
            return
        self.answer({'stat': 'Ok', 'norenordno': number})

    def answer_book(self, login_token):
        """Answers one `OrderBook` the way the next book mode says.

        Args:
            login_token (str): The request's `jKey`.

        Returns:
            None: This method returns nothing.
        """
        state = self.server.state
        with state.lock:
            state.book_requests += 1
            state.book_keys.append(login_token)
            mode = self.next_mode(state.book_modes)
            rows = [dict(row) for row in state.orders]
        if mode == 'reset':
            self.reset()
            return
        if mode == 'error':
            self.answer({'stat': 'Not_Ok', 'emsg': 'Session Expired :  Invalid Session Key'})
            return
        if not rows:
            self.answer({'stat': 'Not_Ok', 'emsg': 'Error Occurred : 5 "no data"'})
            return
        self.answer(rows)


class LocalNorenServer(http.server.ThreadingHTTPServer):
    """The local Noren server, on a free port of 127.0.0.1.

    Attributes:
        daemon_threads (bool): True, so connection threads never keep the process alive.
        state (LocalNorenState): What the server does and has seen.
        serving_thread (threading.Thread): The thread serving requests.
    """

    daemon_threads = True

    def __init__(self):
        """Builds and starts the server.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(('127.0.0.1', 0), LocalNorenHandler)
        self.state = LocalNorenState()
        self.serving_thread = threading.Thread(
            target=self.serve_forever,
            daemon=True,
        )
        self.serving_thread.start()

    def base_url(self):
        """The API's base URL on this server.

        Returns:
            str: The URL, without a trailing slash.
        """
        return f'http://127.0.0.1:{self.server_address[1]}/PiConnectAPI'

    def stop(self):
        """Stops the server.

        Returns:
            None: This method returns nothing.
        """
        self.shutdown()
        self.server_close()


class LocalNorenOrders(NorenOrders):
    """A Noren broker whose orders go to the local Noren server."""

    BROKER_NAME = 'local_noren'
    ACCOUNT_SETTINGS_FIELD = 'username'
    TIMEOUT_SECONDS = (
        1.0,
        1.0,
    )

    def __init__(self, base_url):
        """Builds the broker for one local server.

        Args:
            base_url (str): The server's API base URL.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.BASE_URL = base_url


class LocalPlainOrders(BrokerOrders):
    """A broker that cannot read its order book, whose orders go to the local Noren server."""

    BROKER_NAME = 'local_plain'
    TIMEOUT_SECONDS = (
        1.0,
        1.0,
    )


class ResetRecoverySuite:
    """Runs every check and reports how many passed.

    Attributes:
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Starts with no checks run.

        Returns:
            None: This method returns nothing.
        """
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

    def order_fields(self, price='434.3'):
        """The `jData` fields of a limit sell of 65 NIFTY call units, as Flattrade's request carries them.

        Args:
            price (str): The limit price.

        Returns:
            dict: The fields.
        """
        return {
            'uid': 'FZ00000',
            'actid': 'FZ00000',
            'exch': 'NFO',
            'tsym': 'NIFTY23NOV26C22900',
            'qty': '65',
            'prc': price,
            'trgprc': None,
            'dscqty': '0',
            'prd': 'M',
            'trantype': 'S',
            'prctyp': 'LMT',
            'ret': 'DAY',
            'ordersource': 'API',
            'amo': 'NO',
        }

    def place_request(self, broker_orders, fields):
        """Builds a place-order request the way `NorenOrders.build_place_request` does.

        Args:
            broker_orders (BrokerOrders): The broker, for its URL and body encoding.
            fields (dict): The `jData` fields.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'POST',
            f'{broker_orders.BASE_URL}/PlaceOrder',
            {},
            data=NorenOrders.encoded_body(broker_orders, fields, {'access_token': 'LOCALTOKEN'}),
            shown_form=fields,
            tag=fields.get('remarks'),
        )

    def place(self, server, place_modes, book_modes=None, recorded_before=None):
        """Sends one order to a fresh local server set up for one case.

        Args:
            server (LocalNorenServer): The server.
            place_modes (list): The server's `place_modes`.
            book_modes (list | None): The server's `book_modes`, or None for normal answers.
            recorded_before (list | None): `(fields, seconds_ago)` pairs recorded in the book before the order is sent.

        Returns:
            BrokerAnswer: The answer.
        """
        server.state.place_modes = list(place_modes)
        server.state.book_modes = list(book_modes or [])
        for fields, seconds_ago in recorded_before or []:
            server.state.record(fields, seconds_ago)
        broker_orders = LocalNorenOrders(server.base_url())
        return broker_orders.send_place(self.place_request(broker_orders, self.order_fields()))

    def check_normal_order_never_reads_the_book(self):
        """An order that is answered normally is accepted without reading the book.

        Returns:
            None: This method returns nothing.
        """
        server = LocalNorenServer()
        try:
            answer = self.place(server, ['normal'])
            state = server.state
            self.check(
                'normal order never reads the book',
                answer.outcome == 'accepted' and state.book_requests == 0 and len(state.orders) == 1,
                f'outcome {answer.outcome}, order {answer.order_id}, book reads {state.book_requests}, orders {len(state.orders)}',
            )
        finally:
            server.stop()

    def check_reset_before_arrival_is_sent_again(self):
        """A reset that the broker never saw, with an empty book, is sent again once and accepted.

        Returns:
            None: This method returns nothing.
        """
        server = LocalNorenServer()
        try:
            answer = self.place(server, ['reset_before', 'normal'])
            state = server.state
            self.check(
                'reset before arrival is sent again',
                answer.outcome == 'accepted' and state.place_requests == 2 and len(state.orders) == 1 and state.book_requests == 1,
                f'outcome {answer.outcome}, order {answer.order_id}, place requests {state.place_requests}, orders {len(state.orders)}, book reads {state.book_requests}',
            )
            self.check(
                'the book is read with the order\'s own login',
                state.book_keys == ['LOCALTOKEN'],
                f'book keys {state.book_keys}',
            )
        finally:
            server.stop()

    def check_reset_after_arrival_is_found_not_sent_again(self):
        """A reset after the broker recorded the order takes the order from the book and never sends it twice.

        Returns:
            None: This method returns nothing.
        """
        server = LocalNorenServer()
        try:
            answer = self.place(server, ['reset_after'])
            state = server.state
            recorded = state.orders[0]['norenordno'] if state.orders else None
            self.check(
                'reset after arrival is found, not sent again',
                answer.outcome == 'accepted' and answer.order_id == recorded and state.place_requests == 1 and len(state.orders) == 1,
                f'outcome {answer.outcome}, order {answer.order_id} (book {recorded}), place requests {state.place_requests}, orders {len(state.orders)}; {answer.status_message}',
            )
        finally:
            server.stop()

    def check_other_orders_in_the_book_are_ignored(self):
        """Orders that differ in price, or are older than the request, do not count as the request's, so it is sent again.

        Returns:
            None: This method returns nothing.
        """
        server = LocalNorenServer()
        try:
            other_price = (self.order_fields(price='440.0'), 0.0)
            earlier_same = (self.order_fields(), 30.0)
            answer = self.place(server, ['reset_before', 'normal'], recorded_before=[other_price, earlier_same])
            state = server.state
            self.check(
                'other and earlier orders in the book are ignored',
                answer.outcome == 'accepted' and state.place_requests == 2 and len(state.orders) == 3,
                f'outcome {answer.outcome}, place requests {state.place_requests}, orders {len(state.orders)}',
            )
        finally:
            server.stop()

    def check_two_matches_stay_unknown(self):
        """Two orders that both match leave the outcome unknown and send nothing more.

        Returns:
            None: This method returns nothing.
        """
        server = LocalNorenServer()
        try:
            same = (self.order_fields(), 1.0)
            answer = self.place(server, ['reset_before'], recorded_before=[same, same])
            state = server.state
            self.check(
                'two matching orders stay unknown',
                answer.outcome == 'unknown' and state.place_requests == 1 and 'orders in the book match' in str(answer.status_message),
                f'outcome {answer.outcome}, place requests {state.place_requests}; {answer.status_message}',
            )
        finally:
            server.stop()

    def check_unreadable_book_stays_unknown(self):
        """A book that refuses, or resets too, leaves the outcome unknown and sends nothing more.

        Returns:
            None: This method returns nothing.
        """
        for book_mode in ('error', 'reset'):
            server = LocalNorenServer()
            try:
                answer = self.place(server, ['reset_before'], book_modes=[book_mode])
                state = server.state
                self.check(
                    f'a book that answers {book_mode} stays unknown',
                    answer.outcome == 'unknown' and state.place_requests == 1 and answer.status_code is None,
                    f'outcome {answer.outcome}, place requests {state.place_requests}; {answer.status_message}',
                )
            finally:
                server.stop()

    def check_second_reset_stays_unknown(self):
        """When the order sent again is reset as well, the outcome is unknown and says both happened.

        Returns:
            None: This method returns nothing.
        """
        server = LocalNorenServer()
        try:
            answer = self.place(server, ['reset_before', 'reset_before'])
            state = server.state
            self.check(
                'a second reset stays unknown',
                answer.outcome == 'unknown' and state.place_requests == 2 and 'sent again, which also failed' in str(answer.status_message),
                f'outcome {answer.outcome}, place requests {state.place_requests}; {answer.status_message}',
            )
        finally:
            server.stop()

    def check_broker_without_a_book_is_unchanged(self):
        """A broker that cannot read its book leaves a reset unknown, as before, and never sends twice.

        Returns:
            None: This method returns nothing.
        """
        server = LocalNorenServer()
        try:
            server.state.place_modes = ['reset_before']
            broker_orders = LocalPlainOrders()
            broker_orders.BASE_URL = server.base_url()
            answer = broker_orders.send_place(self.place_request(broker_orders, self.order_fields()))
            state = server.state
            self.check(
                'a broker without a book is unchanged',
                answer.outcome == 'unknown' and answer.connection_reset and state.place_requests == 1 and state.book_requests == 0,
                f'outcome {answer.outcome}, reset {answer.connection_reset}, place requests {state.place_requests}, book reads {state.book_requests}',
            )
        finally:
            server.stop()

    def check_which_errors_are_resets(self):
        """Only a reset or a dropped connection counts as a reset; a timeout never does.

        Returns:
            None: This method returns nothing.
        """
        broker_orders = LocalPlainOrders()
        cases = [
            (
                'Flattrade\'s reset',
                requests.exceptions.ConnectionError(
                    urllib3.exceptions.ProtocolError(
                        'Connection aborted.',
                        ConnectionResetError(104, 'Connection reset by peer'),
                    ),
                ),
                True,
            ),
            (
                'a dropped connection',
                requests.exceptions.ConnectionError(
                    urllib3.exceptions.ProtocolError(
                        'Connection aborted.',
                        http.client.RemoteDisconnected('Remote end closed connection without response'),
                    ),
                ),
                True,
            ),
            (
                'a read timeout',
                requests.exceptions.ReadTimeout('read timed out'),
                False,
            ),
            (
                'a connect timeout',
                requests.exceptions.ConnectTimeout('connect timed out'),
                False,
            ),
            (
                'a refused connection',
                requests.exceptions.ConnectionError(
                    urllib3.exceptions.NewConnectionError(None, 'Connection refused'),
                ),
                False,
            ),
        ]
        observed = []
        all_right = True
        for name, error, expected in cases:
            found = broker_orders.is_connection_reset(error)
            observed.append(f'{name} {found}')
            if found != expected:
                all_right = False
        self.check('only resets count as resets', all_right, ', '.join(observed))

    def run(self):
        """Runs every check.

        Returns:
            int: The exit code: 0 when every check passed, 1 otherwise.
        """
        started = time.monotonic()
        self.check_normal_order_never_reads_the_book()
        self.check_reset_before_arrival_is_sent_again()
        self.check_reset_after_arrival_is_found_not_sent_again()
        self.check_other_orders_in_the_book_are_ignored()
        self.check_two_matches_stay_unknown()
        self.check_unreadable_book_stays_unknown()
        self.check_second_reset_stays_unknown()
        self.check_broker_without_a_book_is_unchanged()
        self.check_which_errors_are_resets()
        total = self.passed + len(self.failed)
        print(f'{self.passed}/{total} checks passed in {time.monotonic() - started:.1f} s.')
        if self.failed:
            return 1
        return 0


if __name__ == '__main__':
    sys.exit(ResetRecoverySuite().run())
