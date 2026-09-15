"""Offline check of the order routes against a recording of their behaviour.

Runs `POST /api/orders/place` and `DELETE /api/orders/cancel` in-process through Flask's test client, with Redis replaced by an in-memory stand-in and every broker call answered by a stub.
For each scenario it keeps the HTTP status, the response body, every request that would have reached a broker (method, URL, parameters, body, headers, timeout and certificate check) and the number of Redis round trips, and compares them with `test_runs/fixtures/order_routes.jsonl`.

No Redis, database, credentials or network are used, and no request leaves the process.
The project's `.env` still has to exist, because importing the blueprint imports `utilities.configurations`.

Typical usage:

    python -m test_runs.order_routes
    python -m test_runs.order_routes --record
"""

import argparse
import copy
import json
import pathlib
import sys
import uuid

import flask
import redis
import requests

from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints import orders as orders_blueprint
from utilities.configurations import api_configuration

BROKER_NAMES = [
    'dhan',
    'flattrade',
    'fyers',
    'groww',
    'indmoney',
    'kotak',
    'shoonya',
    'stoxkart',
    'wisdom_capital',
    'zerodha',
]

API_TOKEN = 'api-token'
MAPPING_DATE = '2026-09-15'
CATALOGUE_PREFIX = f'unified:catalogue:{MAPPING_DATE}:'
FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent / 'fixtures' / 'order_routes.jsonl'
)


class FakeRedis:
    """An in-memory stand-in for the parts of a Redis client the order routes use.

    Every direct command and every pipeline execution counts as one round trip, and a round trip can be made to fail with `redis.RedisError`.

    Attributes:
        strings (dict): String keys to their values.
        hashes (dict): Hash keys to dictionaries of fields and values.
        sorted_sets (dict): Sorted set keys to lists of members, all scored 0.
        round_trips (int): How many round trips have been made.
        failing_round_trip (int | None): The 1-based round trip that raises `redis.RedisError`, or None when none fails.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}
        self.hashes = {}
        self.sorted_sets = {}
        self.round_trips = 0
        self.failing_round_trip = None

    def start_round_trip(self):
        """Counts one round trip and raises when it is the one set to fail.

        Returns:
            None: This method returns nothing.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        self.round_trips = self.round_trips + 1
        if self.round_trips == self.failing_round_trip:
            raise redis.RedisError('stand-in failure')

    def pipeline(self, transaction=True):
        """Starts a pipeline over this stand-in.

        Args:
            transaction (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            FakePipeline: The pipeline.
        """
        del transaction
        return FakePipeline(self)

    def get(self, key):
        """Reads a string key in its own round trip.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when the key is absent.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_get(key)

    def hget(self, key, field):
        """Reads one hash field in its own round trip.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None when absent.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_hget(key, field)

    def hmget(self, key, fields):
        """Reads several hash fields in its own round trip.

        Args:
            key (str): The hash key.
            fields (list): The field names, as strings.

        Returns:
            list: One value or None per field, in the order asked.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_hmget(key, fields)

    def incr(self, key):
        """Adds one to a string key in its own round trip.

        Args:
            key (str): The key.

        Returns:
            int: The value after the increment.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_incr(key)

    def zrangebylex(self, key, minimum, maximum, start=None, num=None):
        """Reads a lexical range of a sorted set in its own round trip.

        Args:
            key (str): The sorted set key.
            minimum (bytes | str): The lower bound, starting with `[` for inclusive or `(` for exclusive.
            maximum (bytes | str): The upper bound, in the same form.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            list: The matching members, as strings.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_zrangebylex(key, minimum, maximum, start, num)

    def run_get(self, key):
        """Reads a string key without counting a round trip.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when absent.
        """
        return self.strings.get(key)

    def run_hget(self, key, field):
        """Reads one hash field without counting a round trip.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None when absent.
        """
        return self.hashes.get(key, {}).get(field)

    def run_hmget(self, key, fields):
        """Reads several hash fields without counting a round trip.

        Args:
            key (str): The hash key.
            fields (list): The field names, as strings.

        Returns:
            list: One value or None per field.
        """
        values = []
        stored_fields = self.hashes.get(key, {})
        for field in fields:
            values.append(stored_fields.get(field))
        return values

    def run_incr(self, key):
        """Adds one to a string key without counting a round trip.

        Args:
            key (str): The key.

        Returns:
            int: The value after the increment.
        """
        value = int(self.strings.get(key) or 0) + 1
        self.strings[key] = str(value)
        return value

    def run_zrangebylex(self, key, minimum, maximum, start, num):
        """Reads a lexical range of a sorted set without counting a round trip.

        Args:
            key (str): The sorted set key.
            minimum (bytes | str): The lower bound, starting with `[` or `(`.
            maximum (bytes | str): The upper bound, starting with `[` or `(`.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            list: The matching members, as strings.
        """
        minimum_bytes = self.as_bytes(minimum)
        maximum_bytes = self.as_bytes(maximum)
        members = sorted(self.sorted_sets.get(key, []), key=self.as_bytes)
        matching = []
        for member in members:
            member_bytes = self.as_bytes(member)
            if not self.above_lower_bound(member_bytes, minimum_bytes):
                continue
            if not self.below_upper_bound(member_bytes, maximum_bytes):
                continue
            matching.append(member)
        if start is not None:
            matching = matching[start:]
        if num is not None:
            matching = matching[:num]
        return matching

    def as_bytes(self, value):
        """Turns a member or bound into bytes for comparison.

        Args:
            value (bytes | str): The value.

        Returns:
            bytes: The value as UTF-8 bytes.
        """
        if isinstance(value, bytes):
            return value
        return value.encode('utf-8')

    def above_lower_bound(self, member_bytes, bound_bytes):
        """Whether a member lies at or above a lexical lower bound.

        Args:
            member_bytes (bytes): The member.
            bound_bytes (bytes): The bound, starting with `[` or `(`, or `-` for no bound.

        Returns:
            bool: True when the member is inside the bound.
        """
        if bound_bytes == b'-':
            return True
        if bound_bytes.startswith(b'['):
            return member_bytes >= bound_bytes[1:]
        return member_bytes > bound_bytes[1:]

    def below_upper_bound(self, member_bytes, bound_bytes):
        """Whether a member lies at or below a lexical upper bound.

        Args:
            member_bytes (bytes): The member.
            bound_bytes (bytes): The bound, starting with `[` or `(`, or `+` for no bound.

        Returns:
            bool: True when the member is inside the bound.
        """
        if bound_bytes == b'+':
            return True
        if bound_bytes.startswith(b'['):
            return member_bytes <= bound_bytes[1:]
        return member_bytes < bound_bytes[1:]


class FakePipeline:
    """A queue of commands sent to a `FakeRedis` in one round trip.

    Attributes:
        fake_redis (FakeRedis): The stand-in the commands run against.
        commands (list): Queued `(command name, arguments)` tuples.
    """

    def __init__(self, fake_redis):
        """Builds an empty pipeline.

        Args:
            fake_redis (FakeRedis): The stand-in the commands run against.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = fake_redis
        self.commands = []

    def get(self, key):
        """Queues a string read.

        Args:
            key (str): The key.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'get',
            [
                key,
            ],
        ))
        return self

    def hget(self, key, field):
        """Queues a hash field read.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'hget',
            [
                key,
                field,
            ],
        ))
        return self

    def hmget(self, key, fields):
        """Queues a read of several hash fields.

        Args:
            key (str): The hash key.
            fields (list): The field names, as strings.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'hmget',
            [
                key,
                list(fields),
            ],
        ))
        return self

    def incr(self, key):
        """Queues an increment.

        Args:
            key (str): The key.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'incr',
            [
                key,
            ],
        ))
        return self

    def execute(self):
        """Runs every queued command in one round trip.

        Returns:
            list: One reply per queued command, in order.

        Raises:
            redis.RedisError: When this round trip is set to fail.
            ValueError: When a queued command is not one the stand-in knows.
        """
        self.fake_redis.start_round_trip()
        replies = []
        for command_name, arguments in self.commands:
            if command_name == 'get':
                replies.append(self.fake_redis.run_get(*arguments))
            elif command_name == 'hget':
                replies.append(self.fake_redis.run_hget(*arguments))
            elif command_name == 'hmget':
                replies.append(self.fake_redis.run_hmget(*arguments))
            elif command_name == 'incr':
                replies.append(self.fake_redis.run_incr(*arguments))
            else:
                raise ValueError(f'unsupported stand-in command: {command_name!r}')
        self.commands = []
        return replies


class FakeResponse:
    """A broker's stubbed HTTP answer.

    Attributes:
        status_code (int): The HTTP status.
        text (str): The body as text.
        json_body (object): The body decoded as JSON, or None when the body is not JSON.
    """

    def __init__(self, status_code, json_body=None, text=None):
        """Builds the answer from a JSON body or from plain text.

        Args:
            status_code (int): The HTTP status.
            json_body (object): The JSON body, or None for a text body.
            text (str | None): The text body, used when there is no JSON body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.json_body = json_body
        if json_body is not None:
            self.text = json.dumps(json_body)
        else:
            self.text = text or ''

    def json(self):
        """Decodes the body as JSON.

        Returns:
            object: The JSON body.

        Raises:
            ValueError: When the body is not JSON.
        """
        if self.json_body is None:
            raise ValueError('the stubbed body is not JSON')
        return self.json_body


class FakeBrokerNetwork:
    """Stands in for every broker's HTTP API by replacing `requests.Session.request`.

    Attributes:
        answer (dict): What the next broker call gets: `status` with `json` or `text`, or `raise` naming a requests exception.
        sent_requests (list): Every request captured since the last reset.
    """

    def __init__(self):
        """Builds the network with an empty success answer.

        Returns:
            None: This method returns nothing.
        """
        self.answer = None
        self.sent_requests = []
        self.reset(None)

    def reset(self, answer):
        """Clears the captured requests and sets the answer for the next calls.

        Args:
            answer (dict | None): The answer, or None for an empty JSON object with HTTP 200.

        Returns:
            None: This method returns nothing.
        """
        if answer is None:
            answer = {
                'status': 200,
                'json': {},
            }
        self.answer = answer
        self.sent_requests = []

    def request(self, method, url, **keyword_arguments):
        """Captures one outgoing request and answers it from `answer`.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **keyword_arguments: The remaining `requests` arguments, such as `data`, `json`, `headers`, `params`, `timeout` and `verify`.

        Returns:
            FakeResponse: The stubbed answer.

        Raises:
            requests.exceptions.ConnectTimeout: When the answer names `ConnectTimeout`.
            requests.exceptions.ReadTimeout: When the answer names `ReadTimeout`.
            requests.exceptions.ConnectionError: When the answer names `ConnectionError`.
        """
        timeout = keyword_arguments.get('timeout')
        if timeout is not None:
            timeout = list(timeout)
        self.sent_requests.append({
            'method': method,
            'url': url,
            'params': keyword_arguments.get('params'),
            'data': keyword_arguments.get('data'),
            'json': keyword_arguments.get('json'),
            'headers': keyword_arguments.get('headers'),
            'timeout': timeout,
            'verify': keyword_arguments.get('verify'),
        })
        exception_name = self.answer.get('raise')
        if exception_name == 'ConnectTimeout':
            raise requests.exceptions.ConnectTimeout('stubbed connect timeout')
        if exception_name == 'ReadTimeout':
            raise requests.exceptions.ReadTimeout('stubbed read timeout')
        if exception_name == 'ConnectionError':
            raise requests.exceptions.ConnectionError('stubbed connection error')
        return FakeResponse(
            self.answer['status'],
            json_body=self.answer.get('json'),
            text=self.answer.get('text'),
        )


class OrderRoutesState:
    """Builds the Redis contents every scenario starts from: logins, settings, instruments and order books.

    Attributes:
        INSTRUMENT_IDENTIFIERS (dict): Short instrument names to their instrument ids.
        ORDER_IDENTIFIERS (dict): Broker names to the id of an open order in that broker's order book.
    """

    INSTRUMENT_IDENTIFIERS = {
        'reliance': '11111111-1111-5111-8111-000000000001',
        'kwil': '11111111-1111-5111-8111-000000000002',
        'nifty_option': '11111111-1111-5111-8111-000000000003',
        'reliance_future': '11111111-1111-5111-8111-000000000004',
        'sensex_option': '11111111-1111-5111-8111-000000000005',
        'twin_first': '11111111-1111-5111-8111-000000000006',
        'twin_second': '11111111-1111-5111-8111-000000000007',
        'partial': '11111111-1111-5111-8111-000000000008',
        'tick_tie': '11111111-1111-5111-8111-000000000009',
        'nifty_index': '11111111-1111-5111-8111-000000000010',
        'crudeoil_future': '11111111-1111-5111-8111-000000000011',
        'usdinr_future': '11111111-1111-5111-8111-000000000012',
        'uncategorised': '11111111-1111-5111-8111-000000000013',
        'niftybees': '11111111-1111-5111-8111-000000000014',
        'mahindra': '11111111-1111-5111-8111-000000000015',
        'broken_handles': '11111111-1111-5111-8111-000000000016',
        'gold_option': '11111111-1111-5111-8111-000000000017',
    }

    ORDER_IDENTIFIERS = {
        'dhan': '112509150000012',
        'flattrade': '26091500000021',
        'fyers': '26091500000013',
        'groww': 'GMK39038RDVL',
        'indmoney': 'EQ-100072817',
        'kotak': '260915000204304',
        'shoonya': '26091500000022',
        'stoxkart': 'SX0001',
        'wisdom_capital': '1234567890',
        'zerodha': '250915000000011',
    }

    def build(self):
        """Builds a fresh stand-in holding the starting contents.

        Returns:
            FakeRedis: The stand-in.
        """
        fake_redis = FakeRedis()
        fake_redis.strings['unified:catalogue:current_date'] = MAPPING_DATE
        fake_redis.strings['unified:catalogue:warm_identifier'] = 'warm-one'
        fake_redis.strings['unified:orders:round_robin'] = '0'
        fake_redis.hashes['last_login'] = self.logins()
        fake_redis.hashes['settings'] = self.settings()
        self.add_instruments(fake_redis)
        self.add_order_books(fake_redis)
        return fake_redis

    def logins(self):
        """Builds the `last_login` hash: the API's token and every broker's login.

        Returns:
            dict: Field names to JSON text.
        """
        logins = {
            'unified_broker_interface': json.dumps({
                'broker_name': 'unified_broker_interface',
                'access_token': API_TOKEN,
                'last_login': '2026-09-15 08:00:00.000000',
                'expires_at': '2099-01-01 00:00:00.000000',
            }),
        }
        for broker_name in BROKER_NAMES:
            login = {
                'broker_name': broker_name,
                'access_token': f'{broker_name}-access-token',
            }
            if broker_name == 'kotak':
                login['sid'] = 'kotak-sid'
                login['base_url'] = 'e21.kotaksecurities.com/'
            logins[broker_name] = json.dumps(login)
        return logins

    def settings(self):
        """Builds the `settings` hash with every account field the routes read.

        Returns:
            dict: Broker names to JSON text.
        """
        settings = {
            'dhan': {
                'client_id': '1100000001',
            },
            'flattrade': {
                'username': 'FT000001',
            },
            'fyers': {
                'app_id': 'FYERSAPP-100',
            },
            'groww': {},
            'indmoney': {},
            'kotak': {},
            'shoonya': {
                'ucc_code': 'FA000001',
            },
            'stoxkart': {
                'ucc_code': 'SX000001',
                'api_key': 'stoxkart-api-key',
            },
            'wisdom_capital': {
                'ucc_code': 'WC000001',
            },
            'zerodha': {
                'api_key': 'kite-api-key',
            },
        }
        encoded = {}
        for broker_name, broker_settings in settings.items():
            encoded[broker_name] = json.dumps(broker_settings)
        return encoded

    def every_broker_handle(self, symbol, token, lot_size, tick_size):
        """Builds order handles for all ten brokers with the same token, lot and tick.

        Flattrade's handle gets no tick size, as Flattrade's files give none.

        Args:
            symbol (str): The base trading symbol, which each broker's symbol is built from.
            token (str): The exchange token every broker shares.
            lot_size (float): The lot size.
            tick_size (float | None): The tick size.

        Returns:
            dict: Broker names to order handles.
        """
        handles = {}
        for broker_name in BROKER_NAMES:
            handles[broker_name] = {
                'broker_token': token,
                'order_symbol': f'{symbol}-{broker_name}',
                'lot_size': lot_size,
                'tick_size': tick_size,
            }
        handles['flattrade']['tick_size'] = None
        return handles

    def add_instrument(self, fake_redis, name, identity, handles, member):
        """Adds one instrument's identity, handles and catalogue member.

        Args:
            fake_redis (FakeRedis): The stand-in to fill.
            name (str): The instrument's key in `INSTRUMENT_IDENTIFIERS`.
            identity (dict): The identity fields other than `instrument_id` and `mapping_date`.
            handles (dict | str): Broker names to order handles, or raw text to store as it is.
            member (str): The catalogue member without its instrument id.

        Returns:
            None: This method returns nothing.
        """
        instrument_id = self.INSTRUMENT_IDENTIFIERS[name]
        full_identity = {
            'instrument_id': instrument_id,
            'exchange': None,
            'segment': None,
            'shape': None,
            'symbol': None,
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
            'mapping_date': MAPPING_DATE,
        }
        full_identity.update(identity)
        identity_hash = fake_redis.hashes.setdefault(
            CATALOGUE_PREFIX + 'identity',
            {},
        )
        identity_hash[instrument_id] = json.dumps(full_identity)
        handles_hash = fake_redis.hashes.setdefault(
            CATALOGUE_PREFIX + 'order_handles',
            {},
        )
        if isinstance(handles, str):
            handles_hash[instrument_id] = handles
        else:
            handles_hash[instrument_id] = json.dumps(handles)
        catalogue_key = (
            CATALOGUE_PREFIX + 'catalogue:' + full_identity['segment']
        )
        members = fake_redis.sorted_sets.setdefault(catalogue_key, [])
        members.append(member + instrument_id)

    def security(self, exchange, segment, symbol):
        """Builds the identity fields of a security.

        Args:
            exchange (str): The exchange.
            segment (str): The exchange-prefixed segment.
            symbol (str): The symbol.

        Returns:
            dict: The identity fields.
        """
        return {
            'exchange': exchange,
            'segment': segment,
            'shape': 'security',
            'symbol': symbol,
        }

    def future(self, exchange, segment, underlying_symbol, expiry_date):
        """Builds the identity fields of a future.

        Args:
            exchange (str): The exchange.
            segment (str): The exchange-prefixed segment.
            underlying_symbol (str): The underlying's symbol.
            expiry_date (str): The expiry date in ISO format.

        Returns:
            dict: The identity fields.
        """
        return {
            'exchange': exchange,
            'segment': segment,
            'shape': 'future',
            'underlying_symbol': underlying_symbol,
            'expiry_date': expiry_date,
        }

    def option(
        self,
        exchange,
        segment,
        underlying_symbol,
        expiry_date,
        strike_price,
        option_type,
    ):
        """Builds the identity fields of an option.

        Args:
            exchange (str): The exchange.
            segment (str): The exchange-prefixed segment.
            underlying_symbol (str): The underlying's symbol.
            expiry_date (str): The expiry date in ISO format.
            strike_price (float): The strike price.
            option_type (str): `CE` or `PE`.

        Returns:
            dict: The identity fields.
        """
        return {
            'exchange': exchange,
            'segment': segment,
            'shape': 'option',
            'underlying_symbol': underlying_symbol,
            'expiry_date': expiry_date,
            'strike_price': strike_price,
            'option_type': option_type,
        }

    def add_instruments(self, fake_redis):
        """Adds every instrument the scenarios use.

        Args:
            fake_redis (FakeRedis): The stand-in to fill.

        Returns:
            None: This method returns nothing.
        """
        self.add_instrument(
            fake_redis,
            'reliance',
            self.security('nse', 'nse_equities', 'RELIANCE'),
            self.every_broker_handle('RELIANCE', '2885', 1.0, 0.05),
            'RELIANCE||||',
        )
        self.add_instrument(
            fake_redis,
            'kwil',
            self.security('bse', 'bse_equities', 'KWIL'),
            self.every_broker_handle('KWIL', '543287', 1.0, 0.01),
            'KWIL||||',
        )
        self.add_instrument(
            fake_redis,
            'nifty_option',
            self.option(
                'nse',
                'nse_equity_index_options',
                'NIFTY',
                '2026-09-29',
                25000.0,
                'CE',
            ),
            self.every_broker_handle('NIFTY26SEP25000CE', '45678', 75.0, 0.05),
            'NIFTY|2026-09-29|00000025000.0000|CE|',
        )
        self.add_instrument(
            fake_redis,
            'reliance_future',
            self.future('nse', 'nse_equity_futures', 'RELIANCE', '2026-09-29'),
            self.every_broker_handle('RELIANCE26SEPFUT', '68777', 500.0, 0.1),
            'RELIANCE|2026-09-29|||',
        )
        self.add_instrument(
            fake_redis,
            'sensex_option',
            self.option(
                'bse',
                'bse_equity_index_options',
                'SENSEX',
                '2026-09-25',
                82000.0,
                'PE',
            ),
            self.every_broker_handle('SENSEX82000PE', '1136555', 20.0, 0.05),
            'SENSEX|2026-09-25|00000082000.0000|PE|',
        )
        for name in (
            'twin_first',
            'twin_second',
        ):
            self.add_instrument(
                fake_redis,
                name,
                self.security('nse', 'nse_equities', 'TWIN'),
                self.every_broker_handle('TWIN', '9001', 1.0, 0.05),
                'TWIN||||',
            )
        self.add_instrument(
            fake_redis,
            'partial',
            self.security('nse', 'nse_equities', 'PARTIAL'),
            self.partial_handles(),
            'PARTIAL||||',
        )
        tie_handles = self.every_broker_handle('TIE', '7002', 1.0, None)
        tie_handles['dhan']['tick_size'] = 0.05
        tie_handles['fyers']['tick_size'] = 0.05
        tie_handles['groww']['tick_size'] = 0.1
        tie_handles['kotak']['tick_size'] = 0.1
        self.add_instrument(
            fake_redis,
            'tick_tie',
            self.security('nse', 'nse_equities', 'TIE'),
            tie_handles,
            'TIE||||',
        )
        self.add_instrument(
            fake_redis,
            'nifty_index',
            self.security('nse', 'nse_equity_indices', 'NIFTY 50'),
            self.every_broker_handle('NIFTY 50', '26000', 1.0, 0.05),
            'NIFTY 50||||',
        )
        crudeoil_handles = self.every_broker_handle(
            'CRUDEOIL26OCTFUT',
            '569900',
            1.0,
            1.0,
        )
        for broker_name in (
            'flattrade',
            'groww',
            'kotak',
            'shoonya',
            'stoxkart',
        ):
            crudeoil_handles[broker_name]['lot_size'] = 100.0
        del crudeoil_handles['indmoney']
        self.add_instrument(
            fake_redis,
            'crudeoil_future',
            self.future(
                'mcx',
                'mcx_commodity_futures',
                'CRUDEOIL',
                '2026-10-19',
            ),
            crudeoil_handles,
            'CRUDEOIL|2026-10-19|||',
        )
        usdinr_handles = self.every_broker_handle(
            'USDINR26SEPFUT',
            '11993',
            1.0,
            0.0025,
        )
        usdinr_handles['stoxkart']['lot_size'] = 1000.0
        self.add_instrument(
            fake_redis,
            'usdinr_future',
            self.future('nse', 'nse_currency_futures', 'USDINR', '2026-09-26'),
            usdinr_handles,
            'USDINR|2026-09-26|||',
        )
        self.add_instrument(
            fake_redis,
            'gold_option',
            self.option(
                'mcx',
                'mcx_commodity_options',
                'GOLD',
                '2026-10-27',
                150000.0,
                'CE',
            ),
            self.every_broker_handle('GOLD26OCT150000CE', '480001', 1.0, 0.5),
            'GOLD|2026-10-27|00000150000.0000|CE|',
        )
        self.add_instrument(
            fake_redis,
            'uncategorised',
            self.security('bse', 'bse_uncategorised', 'ODDROW'),
            self.every_broker_handle('ODDROW', '8001', 1.0, 0.01),
            'ODDROW||||',
        )
        self.add_instrument(
            fake_redis,
            'niftybees',
            self.security('nse', 'nse_exchange_traded_funds', 'NIFTYBEES'),
            self.every_broker_handle('NIFTYBEES', '10576', 1.0, 0.01),
            'NIFTYBEES||||',
        )
        self.add_instrument(
            fake_redis,
            'mahindra',
            self.security('nse', 'nse_equities', 'M&M'),
            self.every_broker_handle('M&M', '2031', 1.0, 0.05),
            'M&M||||',
        )
        self.add_instrument(
            fake_redis,
            'broken_handles',
            self.security('nse', 'nse_equities', 'BROKEN'),
            'not json',
            'BROKEN||||',
        )

    def partial_handles(self):
        """Builds handles that only some brokers carry, some of them unusable.

        Returns:
            dict: Broker names to order handles.
        """
        return {
            'dhan': {
                'broker_token': None,
                'order_symbol': 'PARTIAL',
                'lot_size': 1.0,
                'tick_size': 0.05,
            },
            'groww': {
                'broker_token': '7001',
                'order_symbol': 'PARTIAL',
                'lot_size': 1.0,
                'tick_size': 0.05,
            },
            'kotak': {
                'broker_token': '7001',
                'order_symbol': 'PARTIAL-EQ',
                'lot_size': 1.0,
                'tick_size': 0.05,
            },
            'wisdom_capital': {
                'broker_token': 'ABC',
                'order_symbol': None,
                'lot_size': 1.0,
                'tick_size': 0.05,
            },
        }

    def order_entry(self, status, data, variety=None):
        """Builds one entry of a `<broker>:orders:orders` hash as JSON text.

        Args:
            status (str | None): The normalized order status.
            data (dict): The broker's own copy of the order.
            variety (str | None): The top-level variety Stoxkart's scripts keep, or None to leave it out.

        Returns:
            str: The entry as JSON text.
        """
        entry = {
            'order': {
                'status': status,
            },
            'data': data,
        }
        if variety is not None:
            entry['variety'] = variety
        return json.dumps(entry)

    def add_order_books(self, fake_redis):
        """Adds the order book entries the cancel scenarios look up.

        Args:
            fake_redis (FakeRedis): The stand-in to fill.

        Returns:
            None: This method returns nothing.
        """
        identifiers = self.ORDER_IDENTIFIERS
        books = {}
        for broker_name in BROKER_NAMES:
            books[broker_name] = {}
        books['zerodha'][identifiers['zerodha']] = self.order_entry(
            'OPEN',
            {
                'variety': 'amo',
            },
        )
        books['zerodha']['250915000000099'] = self.order_entry('COMPLETE', {})
        books['dhan'][identifiers['dhan']] = self.order_entry('OPEN', {})
        books['dhan']['BROKENENTRY'] = 'not json'
        books['fyers'][identifiers['fyers']] = self.order_entry('OPEN', {})
        books['fyers']['NOORDERFIELD'] = json.dumps({
            'order': 'not a dictionary',
            'data': 'not a dictionary',
        })
        books['groww'][identifiers['groww']] = self.order_entry(
            'OPEN',
            {
                'segment': 'CASH',
            },
        )
        books['groww']['GMKNOSEGMENT'] = self.order_entry('OPEN', {})
        books['indmoney'][identifiers['indmoney']] = self.order_entry('OPEN', {})
        books['indmoney']['DRV-200000001'] = self.order_entry('OPEN', {})
        books['kotak'][identifiers['kotak']] = self.order_entry('OPEN', {})
        books['flattrade'][identifiers['flattrade']] = self.order_entry(
            'OPEN',
            {},
        )
        books['flattrade']['26091500099999'] = self.order_entry('OPEN', {})
        books['shoonya'][identifiers['shoonya']] = self.order_entry('OPEN', {})
        books['shoonya']['26091500099999'] = self.order_entry(
            'TRIGGER PENDING',
            {},
        )
        books['stoxkart'][identifiers['stoxkart']] = self.order_entry(
            'OPEN',
            {
                'variety': 'NORMAL',
            },
            variety='AMO',
        )
        books['stoxkart']['SX0002'] = self.order_entry(
            'OPEN',
            {
                'variety': 'BO',
            },
        )
        books['wisdom_capital'][identifiers['wisdom_capital']] = (
            self.order_entry(
                'OPEN',
                {
                    'OrderUniqueIdentifier': 'T1',
                },
            )
        )
        books['wisdom_capital']['W-ABC'] = self.order_entry('OPEN', {})
        for broker_name, entries in books.items():
            fake_redis.hashes[f'{broker_name}:orders:orders'] = entries


class OrderRoutesAnswers:
    """Builds the stubbed broker answers the scenarios send back."""

    def json_answer(self, status, body):
        """Builds an answer with a JSON body.

        Args:
            status (int): The HTTP status.
            body (object): The JSON body.

        Returns:
            dict: The answer.
        """
        return {
            'status': status,
            'json': body,
        }

    def text_answer(self, status, text):
        """Builds an answer with a plain text body.

        Args:
            status (int): The HTTP status.
            text (str): The body.

        Returns:
            dict: The answer.
        """
        return {
            'status': status,
            'text': text,
        }

    def raised_answer(self, exception_name):
        """Builds an answer that raises a requests exception instead of answering.

        Args:
            exception_name (str): `ConnectTimeout`, `ReadTimeout` or `ConnectionError`.

        Returns:
            dict: The answer.
        """
        return {
            'raise': exception_name,
        }

    def place_success(self, broker_name):
        """The body a broker sends when it accepts an order.

        Args:
            broker_name (str): The broker.

        Returns:
            dict: The body.
        """
        bodies = {
            'dhan': {
                'orderId': '112509150000012',
                'orderStatus': 'PENDING',
            },
            'flattrade': {
                'stat': 'Ok',
                'norenordno': '26091500000021',
            },
            'fyers': {
                's': 'ok',
                'code': 1101,
                'message': 'Order submitted successfully',
                'id': '26091500000013',
            },
            'groww': {
                'status': 'SUCCESS',
                'payload': {
                    'groww_order_id': 'GMK39038RDVL',
                },
            },
            'indmoney': {
                'status': 'success',
                'data': {
                    'order_id': 'EQ-100072817',
                },
            },
            'kotak': {
                'nOrdNo': '260915000204304',
                'stat': 'Ok',
                'stCode': 200,
            },
            'shoonya': {
                'stat': 'Ok',
                'norenordno': '26091500000022',
            },
            'stoxkart': {
                'status': 'success',
                'message': 'Order Submitted',
                'data': {
                    'order_id': 'SX0001',
                },
            },
            'wisdom_capital': {
                'type': 'success',
                'result': {
                    'AppOrderID': 1234567890,
                },
            },
            'zerodha': {
                'status': 'success',
                'data': {
                    'order_id': '250915000000011',
                },
            },
        }
        return bodies[broker_name]

    def place_refusal(self, broker_name):
        """A body with HTTP 200 in which the broker refuses an order.

        Args:
            broker_name (str): The broker.

        Returns:
            dict: The body.
        """
        bodies = {
            'dhan': {
                'orderId': '0',
                'orderStatus': 'REJECTED',
            },
            'flattrade': {
                'stat': 'Not_Ok',
                'emsg': 'Session Expired :  Invalid Session Key',
            },
            'fyers': {
                's': 'error',
                'code': -50,
                'message': 'Invalid symbol',
            },
            'groww': {
                'status': 'FAILURE',
                'error': {
                    'code': 'GA004',
                    'message': 'Insufficient funds',
                },
            },
            'indmoney': {
                'status': 'error',
                'message': 'insufficient margin',
            },
            'kotak': {
                'stCode': 100008,
                'errMsg': 'unauthorized',
                'stat': 'Not_Ok',
            },
            'shoonya': {
                'stat': 'Not_Ok',
                'emsg': 'Invalid Trading Symbol',
            },
            'stoxkart': {
                'status': 'error',
                'message': 'MARKET IS CLOSE YOU CANNOT PLACE AN ORDER NOW',
            },
            'wisdom_capital': {
                'type': 'error',
                'code': 'e-orders-0005',
                'description': 'Order rejected',
            },
            'zerodha': {
                'status': 'error',
                'message': 'Markets are closed right now.',
            },
        }
        return bodies[broker_name]

    def place_settled_error(self, broker_name):
        """A server error body whose code the broker's rules treat as a settled refusal.

        Args:
            broker_name (str): The broker.

        Returns:
            dict: The body.
        """
        bodies = {
            'dhan': {
                'errorType': 'Order_Error',
                'errorCode': 'DH-906',
                'errorMessage': 'Incorrect order request',
            },
            'flattrade': {
                'stat': 'Not_Ok',
                'emsg': 'Server busy',
            },
            'fyers': {
                's': 'error',
                'code': -99,
                'message': 'Order placement failed',
            },
            'groww': {
                'status': 'FAILURE',
                'error': {
                    'code': 'GA005',
                    'message': 'Order rejected',
                },
            },
            'indmoney': {
                'code': 'validation_error',
                'message': 'invalid quantity',
            },
            'kotak': {
                'stat': 'Not_Ok',
                'errMsg': 'gateway error',
            },
            'shoonya': {
                'stat': 'Not_Ok',
                'emsg': 'Server busy',
            },
            'stoxkart': {
                'status': 'error',
                'message': 'upstream failure',
            },
            'wisdom_capital': {
                'type': 'error',
                'code': 'e-rms-0001',
                'description': 'RMS rejected',
            },
            'zerodha': {
                'status': 'error',
                'error_type': 'OrderException',
                'message': 'Order could not be placed',
            },
        }
        return bodies[broker_name]

    def cancel_refusal(self, broker_name):
        """A body with HTTP 200 in which the broker refuses a cancel.

        Args:
            broker_name (str): The broker.

        Returns:
            dict: The body.
        """
        bodies = {
            'dhan': {
                'errorType': 'Order_Error',
                'errorMessage': 'Order already traded',
            },
            'flattrade': {
                'stat': 'Not_Ok',
                'emsg': 'Rejected : ORA:Order not found to cancel',
            },
            'fyers': {
                's': 'error',
                'message': 'Order not found',
            },
            'groww': {
                'status': 'FAILURE',
                'error': {
                    'message': 'Order already cancelled',
                },
            },
            'indmoney': {
                'status': 'error',
                'message': 'order already executed',
            },
            'kotak': {
                'stat': 'Not_Ok',
                'errMsg': 'Order not found',
            },
            'shoonya': {
                'stat': 'Not_Ok',
                'emsg': 'Rejected : ORA:Order not found to cancel',
            },
            'stoxkart': {
                'status': 'error',
                'message': 'order not found',
            },
            'wisdom_capital': {
                'type': 'error',
                'description': 'Order not found',
            },
            'zerodha': {
                'status': 'error',
                'message': 'Order cannot be cancelled',
            },
        }
        return bodies[broker_name]

    def place_answers(self, broker_name):
        """Every kind of answer a sent order is checked against, apart from plain acceptance.

        Args:
            broker_name (str): The broker.

        Returns:
            list: `(answer name, answer)` tuples.
        """
        return [
            (
                'refusal_in_a_success',
                self.json_answer(200, self.place_refusal(broker_name)),
            ),
            (
                'empty_success',
                self.json_answer(200, {}),
            ),
            (
                'text_success',
                self.text_answer(200, 'OK'),
            ),
            (
                'client_error',
                self.json_answer(
                    400,
                    {
                        'message': 'bad request',
                    },
                ),
            ),
            (
                'settled_server_error',
                self.json_answer(500, self.place_settled_error(broker_name)),
            ),
            (
                'nested_server_error',
                self.json_answer(
                    502,
                    {
                        'error': {
                            'code': 'GA001',
                            'message': 'nested failure',
                        },
                    },
                ),
            ),
            (
                'plain_server_error',
                self.json_answer(
                    500,
                    {
                        'message': 'internal error',
                    },
                ),
            ),
            (
                'text_server_error',
                self.text_answer(503, 'Service Unavailable'),
            ),
            (
                'connect_timeout',
                self.raised_answer('ConnectTimeout'),
            ),
            (
                'read_timeout',
                self.raised_answer('ReadTimeout'),
            ),
            (
                'connection_error',
                self.raised_answer('ConnectionError'),
            ),
        ]

    def cancel_answers(self, broker_name):
        """Every kind of answer a sent cancel is checked against.

        Args:
            broker_name (str): The broker.

        Returns:
            list: `(answer name, answer)` tuples.
        """
        return [
            (
                'success',
                self.json_answer(
                    200,
                    {
                        'status': 'success',
                        'stat': 'Ok',
                        's': 'ok',
                        'type': 'success',
                    },
                ),
            ),
            (
                'refusal_in_a_success',
                self.json_answer(200, self.cancel_refusal(broker_name)),
            ),
            (
                'text_success',
                self.text_answer(200, 'OK'),
            ),
            (
                'client_error',
                self.json_answer(
                    400,
                    {
                        'errorMessage': 'bad request',
                    },
                ),
            ),
            (
                'nested_client_error',
                self.json_answer(
                    404,
                    {
                        'error': {
                            'message': 'nested not found',
                        },
                    },
                ),
            ),
            (
                'server_error',
                self.json_answer(
                    500,
                    {
                        'message': 'internal error',
                    },
                ),
            ),
            (
                'connect_timeout',
                self.raised_answer('ConnectTimeout'),
            ),
            (
                'read_timeout',
                self.raised_answer('ReadTimeout'),
            ),
        ]


class OrderRoutesScenarios:
    """Builds the list of scenarios the suite runs.

    A scenario is a dictionary with a `name` and either one request or a list of `steps`.
    A scenario may also name `selector` and `priority`, the broker selector configuration its blueprint is built with, or set `expect_construction_error` when building the blueprint should fail.
    A request has `route` (`place` or `cancel`), and optionally `headers`, `body` (a dictionary), `raw_body` (text), `query`, `counter` (the value the round-robin `INCR` returns), `excluded` (brokers to exclude), `answer` (the stubbed broker answer), `failing_round_trip`, and `changes` (Redis edits made before the request).

    Attributes:
        answers (OrderRoutesAnswers): The stubbed broker answers.
    """

    def __init__(self):
        """Builds the scenario builder.

        Returns:
            None: This method returns nothing.
        """
        self.answers = OrderRoutesAnswers()

    def build(self):
        """Builds every scenario, in the order they are run and recorded.

        Returns:
            list: The scenarios.
        """
        scenarios = []
        scenarios.extend(self.place_token_scenarios())
        scenarios.extend(self.place_body_scenarios())
        scenarios.extend(self.place_instrument_scenarios())
        scenarios.extend(self.place_routing_scenarios())
        scenarios.extend(self.place_broker_request_scenarios())
        scenarios.extend(self.place_answer_scenarios())
        scenarios.extend(self.place_cache_scenarios())
        scenarios.extend(self.place_selector_scenarios())
        scenarios.extend(self.cancel_parameter_scenarios())
        scenarios.extend(self.cancel_lookup_scenarios())
        scenarios.extend(self.cancel_broker_scenarios())
        return scenarios

    def counter_for(self, broker_name):
        """The round-robin counter value that gives a broker the turn when no broker is excluded.

        Args:
            broker_name (str): The broker.

        Returns:
            int: The value `INCR` should return.
        """
        return BROKER_NAMES.index(broker_name) + len(BROKER_NAMES)

    def string_change(self, key, value):
        """Builds an edit that sets or deletes a string key.

        Args:
            key (str): The key.
            value (str | None): The new value, or None to delete the key.

        Returns:
            dict: The edit.
        """
        return {
            'kind': 'string',
            'key': key,
            'value': value,
        }

    def hash_change(self, key, field, value):
        """Builds an edit that sets or deletes a hash field.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str | None): The new value, or None to delete the field.

        Returns:
            dict: The edit.
        """
        return {
            'kind': 'hash',
            'key': key,
            'field': field,
            'value': value,
        }

    def market_order(self, **overrides):
        """Builds a dry-run MARKET buy of ten RELIANCE shares by instrument id, with fields replaced, added or removed.

        Args:
            **overrides: Body fields to replace or add; a value of None removes the field.

        Returns:
            dict: The request body.
        """
        body = {
            'instrument_id': (
                OrderRoutesState.INSTRUMENT_IDENTIFIERS['reliance']
            ),
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
            'dry_run': True,
        }
        for field_name, value in overrides.items():
            if value is None:
                body.pop(field_name, None)
            else:
                body[field_name] = value
        return body

    def by_fields(self, exchange, segment, **fields):
        """Builds a dry-run MARKET buy that names its instrument by identity fields instead of an id.

        Args:
            exchange (str): The exchange field.
            segment (str): The segment field.
            **fields: The identity fields and any other body fields to replace or add.

        Returns:
            dict: The request body.
        """
        return self.market_order(
            instrument_id=None,
            exchange=exchange,
            segment=segment,
            **fields,
        )

    def by_identifier(self, name, **fields):
        """Builds a dry-run MARKET buy of one of the stand-in's instruments by its id.

        Args:
            name (str): The instrument's key in `OrderRoutesState.INSTRUMENT_IDENTIFIERS`.
            **fields: Other body fields to replace or add.

        Returns:
            dict: The request body.
        """
        return self.market_order(
            instrument_id=OrderRoutesState.INSTRUMENT_IDENTIFIERS[name],
            **fields,
        )

    def place(self, name, body, **settings):
        """Builds one place scenario.

        Args:
            name (str): The scenario name.
            body (dict | None): The request body.
            **settings: Any other scenario keys, such as `counter`, `answer` or `changes`.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'route': 'place',
            'body': body,
        }
        scenario.update(settings)
        return scenario

    def cancel(self, name, body, **settings):
        """Builds one cancel scenario.

        Args:
            name (str): The scenario name.
            body (dict | None): The request body.
            **settings: Any other scenario keys, such as `query`, `answer` or `changes`.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'route': 'cancel',
            'body': body,
        }
        scenario.update(settings)
        return scenario

    def cancel_body(self, order_id, **fields):
        """Builds a cancel request body.

        Args:
            order_id (object): The order id field.
            **fields: Other fields, such as `broker` or `dry_run`.

        Returns:
            dict: The request body.
        """
        body = {
            'order_id': order_id,
        }
        body.update(fields)
        return body

    def place_token_scenarios(self):
        """Builds the place scenarios about the access token and the first Redis read.

        Returns:
            list: The scenarios.
        """
        expired_token = json.dumps({
            'access_token': API_TOKEN,
            'expires_at': '2020-01-01 00:00:00.000000',
        })
        token_without_expiry = json.dumps({
            'access_token': API_TOKEN,
        })
        return [
            self.place(
                'token_header_missing',
                self.market_order(),
                headers={},
            ),
            self.place(
                'token_wrong',
                self.market_order(),
                headers={
                    'access-token': 'wrong',
                },
            ),
            self.place(
                'token_expired',
                self.market_order(),
                changes=[
                    self.hash_change(
                        'last_login',
                        'unified_broker_interface',
                        expired_token,
                    ),
                ],
            ),
            self.place(
                'token_without_expiry',
                self.market_order(),
                changes=[
                    self.hash_change(
                        'last_login',
                        'unified_broker_interface',
                        token_without_expiry,
                    ),
                ],
            ),
            self.place(
                'token_document_not_json',
                self.market_order(),
                changes=[
                    self.hash_change(
                        'last_login',
                        'unified_broker_interface',
                        'not json',
                    ),
                ],
            ),
            self.place(
                'token_document_missing',
                self.market_order(),
                changes=[
                    self.hash_change(
                        'last_login',
                        'unified_broker_interface',
                        None,
                    ),
                ],
            ),
            self.place(
                'redis_fails_first_round_trip',
                self.market_order(),
                failing_round_trip=1,
            ),
        ]

    def place_body_scenarios(self):
        """Builds the place scenarios about the order fields in the body.

        Returns:
            list: The scenarios.
        """
        return [
            self.place('body_not_json', None, raw_body='not json'),
            self.place('body_is_a_list', None, raw_body='[1, 2]'),
            self.place(
                'transaction_type_invalid',
                self.market_order(transaction_type='HOLD'),
            ),
            self.place(
                'transaction_type_lower_case',
                self.market_order(transaction_type=' sell '),
            ),
            self.place('product_invalid', self.market_order(product='BO')),
            self.place(
                'order_type_invalid',
                self.market_order(order_type='STOP'),
            ),
            self.place('validity_invalid', self.market_order(validity='GTC')),
            self.place('quantity_missing', self.market_order(quantity=None)),
            self.place('quantity_empty', self.market_order(quantity='')),
            self.place('quantity_zero', self.market_order(quantity=0)),
            self.place('quantity_fraction', self.market_order(quantity=1.5)),
            self.place('quantity_text', self.market_order(quantity='abc')),
            self.place('quantity_as_string', self.market_order(quantity='10')),
            self.place(
                'disclosed_quantity_negative',
                self.market_order(disclosed_quantity=-1),
            ),
            self.place(
                'disclosed_quantity_above_quantity',
                self.market_order(disclosed_quantity=11),
            ),
            self.place(
                'price_negative',
                self.market_order(order_type='LIMIT', price='-1'),
            ),
            self.place(
                'price_not_a_number',
                self.market_order(order_type='LIMIT', price='NaN'),
            ),
            self.place(
                'price_infinite',
                self.market_order(order_type='LIMIT', price='Infinity'),
            ),
            self.place(
                'limit_without_price',
                self.market_order(order_type='LIMIT'),
            ),
            self.place('market_with_price', self.market_order(price='100')),
            self.place(
                'stop_loss_without_trigger',
                self.market_order(order_type='SL', price='100'),
            ),
            self.place(
                'limit_with_trigger',
                self.market_order(
                    order_type='LIMIT',
                    price='100',
                    trigger_price='99',
                ),
            ),
            self.place(
                'stop_loss_market_with_price',
                self.market_order(
                    order_type='SL-M',
                    price='100',
                    trigger_price='99',
                ),
            ),
            self.place(
                'after_market_invalid',
                self.market_order(after_market='maybe'),
            ),
            self.place(
                'after_market_yes',
                self.market_order(after_market='yes'),
            ),
            self.place(
                'dry_run_invalid',
                self.market_order(dry_run='perhaps'),
            ),
            self.place('tag_with_spaces', self.market_order(tag='bad tag!')),
            self.place('tag_too_long', self.market_order(tag='A' * 21)),
            self.place('tag_not_text', self.market_order(tag=123)),
            self.place('tag_padded', self.market_order(tag=' ok12 ')),
        ]

    def place_instrument_scenarios(self):
        """Builds the place scenarios about finding and checking the instrument.

        Returns:
            list: The scenarios.
        """
        identifiers = OrderRoutesState.INSTRUMENT_IDENTIFIERS
        return [
            self.place(
                'instrument_id_not_uuid',
                self.market_order(instrument_id='nope'),
            ),
            self.place(
                'instrument_id_upper_case',
                self.market_order(
                    instrument_id=identifiers['reliance'].upper(),
                ),
            ),
            self.place(
                'instrument_id_unknown',
                self.market_order(
                    instrument_id='22222222-2222-5222-8222-222222222222',
                ),
            ),
            self.place(
                'instrument_handles_not_json',
                self.by_identifier('broken_handles'),
            ),
            self.place(
                'instrument_is_an_index',
                self.by_identifier('nifty_index'),
            ),
            self.place(
                'instrument_is_uncategorised',
                self.by_identifier('uncategorised'),
            ),
            self.place(
                'instrument_is_a_currency_future',
                self.by_identifier('usdinr_future', quantity=1000),
            ),
            self.place(
                'instrument_is_a_commodity_future',
                self.by_identifier('crudeoil_future', quantity=100),
            ),
            self.place(
                'instrument_is_a_commodity_option',
                self.by_identifier('gold_option', quantity=1),
            ),
            self.place(
                'exchange_fund_by_id',
                self.by_identifier('niftybees'),
            ),
            self.place(
                'fields_without_exchange',
                self.market_order(
                    instrument_id=None,
                    segment='equities',
                    symbol='RELIANCE',
                ),
            ),
            self.place(
                'fields_exchange_mcx',
                self.by_fields(
                    'mcx',
                    'commodity_futures',
                    underlying_symbol='CRUDEOIL',
                    expiry_date='2026-10-19',
                    quantity=100,
                ),
            ),
            self.place(
                'fields_exchange_ncdex',
                self.by_fields(
                    'ncdex',
                    'commodity_futures',
                    underlying_symbol='BAJRA',
                    expiry_date='2026-10-20',
                ),
            ),
            self.place(
                'fields_currency_segment',
                self.by_fields(
                    'nse',
                    'currency_futures',
                    underlying_symbol='USDINR',
                    expiry_date='2026-09-26',
                    quantity=1000,
                ),
            ),
            self.place(
                'fields_commodity_option_segment',
                self.by_fields(
                    'mcx',
                    'commodity_options',
                    underlying_symbol='GOLD',
                    expiry_date='2026-10-27',
                    strike_price='150000',
                    option_type='CE',
                    quantity=1,
                ),
            ),
            self.place(
                'fields_segment_unknown',
                self.by_fields('nse', 'spot_gold', symbol='GOLD'),
            ),
            self.place(
                'fields_segment_index',
                self.by_fields('nse', 'equity_indices', symbol='NIFTY 50'),
            ),
            self.place(
                'fields_segment_uncategorised',
                self.by_fields('bse', 'uncategorised', symbol='ODDROW'),
            ),
            self.place(
                'fields_security_without_symbol',
                self.by_fields('nse', 'equities'),
            ),
            self.place(
                'fields_security_lower_case_prefixed',
                self.by_fields('NSE', 'nse_equities', symbol='reliance'),
            ),
            self.place(
                'fields_exchange_fund',
                self.by_fields(
                    'nse',
                    'exchange_traded_funds',
                    symbol='NIFTYBEES',
                ),
            ),
            self.place(
                'fields_future_without_expiry',
                self.by_fields(
                    'nse',
                    'equity_futures',
                    underlying_symbol='RELIANCE',
                    quantity=500,
                ),
            ),
            self.place(
                'fields_future_bad_expiry',
                self.by_fields(
                    'nse',
                    'equity_futures',
                    underlying_symbol='RELIANCE',
                    expiry_date='29-09-2026',
                    quantity=500,
                ),
            ),
            self.place(
                'fields_future',
                self.by_fields(
                    'nse',
                    'equity_futures',
                    underlying_symbol='RELIANCE',
                    expiry_date='2026-09-29',
                    quantity=500,
                ),
            ),
            self.place(
                'fields_option_bad_strike',
                self.by_fields(
                    'nse',
                    'equity_index_options',
                    underlying_symbol='NIFTY',
                    expiry_date='2026-09-29',
                    strike_price='abc',
                    option_type='CE',
                    quantity=75,
                ),
            ),
            self.place(
                'fields_option_bad_type',
                self.by_fields(
                    'nse',
                    'equity_index_options',
                    underlying_symbol='NIFTY',
                    expiry_date='2026-09-29',
                    strike_price='25000',
                    option_type='CALL',
                    quantity=75,
                ),
            ),
            self.place(
                'fields_option',
                self.by_fields(
                    'nse',
                    'equity_index_options',
                    underlying_symbol='nifty',
                    expiry_date='2026-09-29',
                    strike_price='25000.00',
                    option_type='ce',
                    quantity=75,
                ),
            ),
            self.place(
                'fields_not_mapped',
                self.by_fields('nse', 'equities', symbol='NOSUCH'),
            ),
            self.place(
                'fields_ambiguous',
                self.by_fields('nse', 'equities', symbol='TWIN'),
            ),
            self.place(
                'fields_redis_fails_on_catalogue',
                self.by_fields('nse', 'equities', symbol='RELIANCE'),
                failing_round_trip=2,
            ),
            self.place(
                'redis_fails_second_round_trip',
                self.market_order(),
                failing_round_trip=2,
            ),
            self.place(
                'mapping_date_missing',
                self.market_order(),
                changes=[
                    self.string_change('unified:catalogue:current_date', None),
                ],
            ),
            self.place(
                'every_broker_excluded',
                self.market_order(),
                excluded=list(BROKER_NAMES),
            ),
            self.place(
                'lot_size_not_whole',
                self.by_identifier('reliance_future', quantity=250),
            ),
            self.place(
                'price_not_whole_ticks',
                self.market_order(order_type='LIMIT', price='100.03'),
            ),
            self.place(
                'trigger_not_whole_ticks',
                self.market_order(order_type='SL-M', trigger_price='100.03'),
            ),
            self.place(
                'tick_size_tie_skips_the_check',
                self.by_identifier(
                    'tick_tie',
                    order_type='LIMIT',
                    price='100.03',
                ),
            ),
        ]

    def place_routing_scenarios(self):
        """Builds the place scenarios about which broker is chosen or passed over.

        Returns:
            list: The scenarios.
        """
        partial_order = self.by_identifier('partial')
        every_login_removed = []
        for broker_name in BROKER_NAMES:
            every_login_removed.append(
                self.hash_change('last_login', broker_name, None),
            )
        kotak_login_without_sid = json.dumps({
            'access_token': 'kotak-access-token',
        })
        login_without_token = json.dumps({
            'access_token': None,
        })
        return [
            self.place(
                'turn_after_exclusions',
                self.market_order(),
                counter=10,
                excluded=[
                    'dhan',
                    'zerodha',
                ],
            ),
            self.place(
                'turn_skips_brokers_without_mapping_from_dhan',
                partial_order,
                counter=self.counter_for('dhan'),
            ),
            self.place(
                'turn_skips_brokers_without_mapping_from_wisdom_capital',
                partial_order,
                counter=self.counter_for('wisdom_capital'),
            ),
            self.place(
                'turn_skips_broker_without_login',
                self.market_order(),
                counter=self.counter_for('fyers'),
                changes=[
                    self.hash_change('last_login', 'fyers', None),
                ],
            ),
            self.place(
                'turn_skips_broker_whose_login_is_not_json',
                self.market_order(),
                counter=self.counter_for('dhan'),
                changes=[
                    self.hash_change('last_login', 'dhan', 'not json'),
                ],
            ),
            self.place(
                'turn_skips_broker_whose_login_has_no_token',
                self.market_order(),
                counter=self.counter_for('groww'),
                changes=[
                    self.hash_change(
                        'last_login',
                        'groww',
                        login_without_token,
                    ),
                ],
            ),
            self.place(
                'turn_skips_kotak_without_sid',
                self.market_order(),
                counter=self.counter_for('kotak'),
                changes=[
                    self.hash_change(
                        'last_login',
                        'kotak',
                        kotak_login_without_sid,
                    ),
                ],
            ),
            self.place(
                'turn_skips_broker_without_settings',
                self.market_order(),
                counter=self.counter_for('zerodha'),
                changes=[
                    self.hash_change('settings', 'zerodha', None),
                ],
            ),
            self.place(
                'turn_skips_broker_whose_settings_are_not_json',
                self.market_order(),
                counter=self.counter_for('stoxkart'),
                changes=[
                    self.hash_change('settings', 'stoxkart', 'not json'),
                ],
            ),
            self.place(
                'turn_skips_broker_whose_settings_are_a_list',
                self.market_order(),
                counter=self.counter_for('shoonya'),
                changes=[
                    self.hash_change('settings', 'shoonya', '[]'),
                ],
            ),
            self.place(
                'no_broker_can_take_the_order',
                self.market_order(),
                counter=self.counter_for('dhan'),
                changes=every_login_removed,
            ),
        ]

    def place_variants(self):
        """Builds the order bodies every broker's request is recorded for.

        Returns:
            list: `(variant name, body)` tuples, with `dry_run` removed.
        """
        return [
            (
                'market_buy_mis_nse_equity',
                self.market_order(dry_run=None),
            ),
            (
                'limit_sell_cnc_bse_equity_ioc_tag',
                self.by_fields(
                    'bse',
                    'equities',
                    dry_run=None,
                    symbol='KWIL',
                    transaction_type='SELL',
                    product='CNC',
                    order_type='LIMIT',
                    quantity=5,
                    price='101.25',
                    validity='ioc',
                    tag='abc123',
                    disclosed_quantity=2,
                ),
            ),
            (
                'stop_loss_buy_nrml_nse_option_after_market',
                self.by_fields(
                    'nse',
                    'equity_index_options',
                    dry_run=None,
                    underlying_symbol='NIFTY',
                    expiry_date='2026-09-29',
                    strike_price='25000',
                    option_type='CE',
                    product='NRML',
                    order_type='SL',
                    quantity=150,
                    price='120.05',
                    trigger_price='119.95',
                    after_market=True,
                ),
            ),
            (
                'stop_loss_market_sell_nrml_nse_future_tag',
                self.by_identifier(
                    'reliance_future',
                    dry_run=None,
                    transaction_type='SELL',
                    product='NRML',
                    order_type='SL-M',
                    quantity=500,
                    trigger_price='2950.10',
                    tag='T1',
                ),
            ),
            (
                'limit_buy_mis_bse_option_disclosed',
                self.by_fields(
                    'bse',
                    'bse_equity_index_options',
                    dry_run=None,
                    underlying_symbol='SENSEX',
                    expiry_date='2026-09-25',
                    strike_price='82000',
                    option_type='PE',
                    order_type='LIMIT',
                    quantity=40,
                    price='250.5',
                    disclosed_quantity=20,
                ),
            ),
            (
                'limit_buy_cnc_symbol_with_ampersand',
                self.by_identifier(
                    'mahindra',
                    dry_run=None,
                    product='CNC',
                    order_type='LIMIT',
                    quantity=1,
                    price='3000.05',
                ),
            ),
        ]

    def place_broker_request_scenarios(self):
        """Builds a dry run and a sent order for every broker and every variant.

        Returns:
            list: The scenarios.
        """
        scenarios = []
        for broker_name in BROKER_NAMES:
            for variant_name, body in self.place_variants():
                dry_run_body = dict(body)
                dry_run_body['dry_run'] = True
                scenarios.append(self.place(
                    f'{broker_name}_{variant_name}_dry_run',
                    dry_run_body,
                    counter=self.counter_for(broker_name),
                ))
                success = self.answers.place_success(broker_name)
                scenarios.append(self.place(
                    f'{broker_name}_{variant_name}_sent',
                    body,
                    counter=self.counter_for(broker_name),
                    answer=self.answers.json_answer(200, success),
                ))
        return scenarios

    def place_answer_scenarios(self):
        """Builds a sent MARKET order for every broker and every kind of broker answer.

        Returns:
            list: The scenarios.
        """
        scenarios = []
        body = self.market_order(dry_run=None)
        for broker_name in BROKER_NAMES:
            for answer_name, answer in self.answers.place_answers(broker_name):
                scenarios.append(self.place(
                    f'{broker_name}_answer_{answer_name}',
                    body,
                    counter=self.counter_for(broker_name),
                    answer=answer,
                ))
        return scenarios

    def place_cache_scenarios(self):
        """Builds scenarios of several orders through one blueprint, which show what a worker remembers between requests.

        Returns:
            list: The scenarios.
        """
        identifiers = OrderRoutesState.INSTRUMENT_IDENTIFIERS
        kwil_by_fields = self.by_fields('bse', 'equities', symbol='KWIL')
        reliance_by_identifier = self.market_order()
        changed_handles = OrderRoutesState().every_broker_handle(
            'RELIANCE',
            '2885',
            3.0,
            0.05,
        )
        return [
            {
                'name': 'repeat_order_by_fields',
                'steps': [
                    self.place('first', kwil_by_fields),
                    self.place('second', kwil_by_fields),
                ],
            },
            {
                'name': 'repeat_order_by_identifier',
                'steps': [
                    self.place('first', reliance_by_identifier),
                    self.place('second', reliance_by_identifier),
                ],
            },
            {
                'name': 'repeat_order_after_a_new_warm',
                'steps': [
                    self.place('first', kwil_by_fields),
                    self.place(
                        'second',
                        kwil_by_fields,
                        changes=[
                            self.string_change(
                                'unified:catalogue:warm_identifier',
                                'warm-two',
                            ),
                        ],
                    ),
                ],
            },
            {
                'name': 'repeat_order_without_a_warm_identifier',
                'steps': [
                    self.place(
                        'first',
                        kwil_by_fields,
                        changes=[
                            self.string_change(
                                'unified:catalogue:warm_identifier',
                                None,
                            ),
                        ],
                    ),
                    self.place('second', kwil_by_fields),
                ],
            },
            {
                'name': 'repeat_order_after_the_mapping_date_moves',
                'steps': [
                    self.place('first', kwil_by_fields),
                    self.place(
                        'second',
                        kwil_by_fields,
                        changes=[
                            self.string_change(
                                'unified:catalogue:current_date',
                                '2026-09-16',
                            ),
                        ],
                    ),
                ],
            },
            {
                'name': 'repeat_order_after_handles_change_within_one_warm',
                'steps': [
                    self.place('first', reliance_by_identifier),
                    self.place(
                        'second',
                        reliance_by_identifier,
                        changes=[
                            self.hash_change(
                                CATALOGUE_PREFIX + 'order_handles',
                                identifiers['reliance'],
                                json.dumps(changed_handles),
                            ),
                        ],
                    ),
                ],
            },
        ]

    def place_selector_scenarios(self):
        """Builds the place scenarios about which broker selector a blueprint is built with.

        Returns:
            list: The scenarios.
        """
        return [
            self.place(
                'fixed_priority_without_a_preference',
                self.market_order(),
                selector='fixed_priority',
            ),
            self.place(
                'fixed_priority_with_a_preference',
                self.market_order(),
                selector='fixed_priority',
                priority=[
                    'zerodha',
                    'kotak',
                ],
            ),
            self.place(
                'fixed_priority_passes_over_a_broker_that_cannot_take_it',
                self.market_order(),
                selector='fixed_priority',
                priority=[
                    'fyers',
                    'kotak',
                ],
                changes=[
                    self.hash_change('last_login', 'fyers', None),
                ],
            ),
            self.place(
                'fixed_priority_never_offers_an_excluded_broker',
                self.market_order(),
                selector='fixed_priority',
                priority=[
                    'zerodha',
                ],
                excluded=[
                    'zerodha',
                ],
            ),
            self.place(
                'fixed_priority_ignores_unknown_names',
                self.market_order(),
                selector='fixed_priority',
                priority=[
                    'upstox',
                    'groww',
                ],
            ),
            self.place(
                'fixed_priority_sends_a_sequence_to_one_broker',
                None,
                selector='fixed_priority',
                steps=[
                    self.place('first', self.market_order()),
                    self.place('second', self.market_order()),
                ],
            ),
            self.place(
                'unknown_selector_stops_the_blueprint',
                self.market_order(),
                selector='random_choice',
                expect_construction_error=True,
            ),
        ]

    def cancel_parameter_scenarios(self):
        """Builds the cancel scenarios about the token and the parameters.

        Returns:
            list: The scenarios.
        """
        dhan_order = OrderRoutesState.ORDER_IDENTIFIERS['dhan']
        expired_token = json.dumps({
            'access_token': API_TOKEN,
            'expires_at': '2020-01-01 00:00:00.000000',
        })
        return [
            self.cancel(
                'cancel_token_header_missing',
                self.cancel_body(dhan_order),
                headers={},
            ),
            self.cancel('cancel_body_is_a_list', None, raw_body='[1]'),
            self.cancel(
                'cancel_body_not_json_without_order_id',
                None,
                raw_body='not json',
            ),
            self.cancel('cancel_order_id_missing', {}),
            self.cancel(
                'cancel_order_id_bad_characters',
                self.cancel_body('abc$'),
            ),
            self.cancel(
                'cancel_order_id_too_long',
                self.cancel_body('A' * 65),
            ),
            self.cancel(
                'cancel_order_id_number',
                self.cancel_body(1234567890, dry_run=True),
            ),
            self.cancel(
                'cancel_order_id_boolean',
                self.cancel_body(True),
            ),
            self.cancel(
                'cancel_order_id_in_query',
                None,
                query={
                    'order_id': dhan_order,
                    'dry_run': 'true',
                },
            ),
            self.cancel(
                'cancel_broker_unknown',
                self.cancel_body(dhan_order, broker='upstox'),
            ),
            self.cancel(
                'cancel_broker_in_query',
                None,
                query={
                    'order_id': '26091500099999',
                    'broker': 'Shoonya',
                    'dry_run': '1',
                },
            ),
            self.cancel(
                'cancel_dry_run_invalid',
                self.cancel_body(dhan_order, dry_run='maybe'),
            ),
            self.cancel(
                'cancel_redis_fails',
                self.cancel_body(dhan_order),
                failing_round_trip=1,
            ),
            self.cancel(
                'cancel_token_wrong',
                self.cancel_body(dhan_order),
                headers={
                    'access-token': 'wrong',
                },
            ),
            self.cancel(
                'cancel_token_expired',
                self.cancel_body(dhan_order),
                changes=[
                    self.hash_change(
                        'last_login',
                        'unified_broker_interface',
                        expired_token,
                    ),
                ],
            ),
        ]

    def cancel_lookup_scenarios(self):
        """Builds the cancel scenarios about finding the order and what its broker needs.

        Returns:
            list: The scenarios.
        """
        identifiers = OrderRoutesState.ORDER_IDENTIFIERS
        kotak_login_without_sid = json.dumps({
            'access_token': 'kotak-access-token',
        })
        return [
            self.cancel(
                'cancel_order_not_found',
                self.cancel_body('NOSUCHORDER'),
            ),
            self.cancel(
                'cancel_entry_not_json',
                self.cancel_body('BROKENENTRY'),
            ),
            self.cancel(
                'cancel_entry_fields_not_dictionaries',
                self.cancel_body('NOORDERFIELD', dry_run=True),
            ),
            self.cancel(
                'cancel_order_at_two_brokers',
                self.cancel_body('26091500099999'),
            ),
            self.cancel(
                'cancel_order_at_two_brokers_with_broker',
                self.cancel_body(
                    '26091500099999',
                    broker='shoonya',
                    dry_run=True,
                ),
            ),
            self.cancel(
                'cancel_broker_given_but_not_holding',
                self.cancel_body(identifiers['dhan'], broker='zerodha'),
            ),
            self.cancel(
                'cancel_order_finished',
                self.cancel_body('250915000000099'),
            ),
            self.cancel(
                'cancel_broker_without_login',
                self.cancel_body(identifiers['dhan']),
                changes=[
                    self.hash_change('last_login', 'dhan', None),
                ],
            ),
            self.cancel(
                'cancel_kotak_without_sid',
                self.cancel_body(identifiers['kotak']),
                changes=[
                    self.hash_change(
                        'last_login',
                        'kotak',
                        kotak_login_without_sid,
                    ),
                ],
            ),
            self.cancel(
                'cancel_broker_without_settings',
                self.cancel_body(identifiers['fyers']),
                changes=[
                    self.hash_change('settings', 'fyers', '{}'),
                ],
            ),
            self.cancel(
                'cancel_dhan_without_settings',
                self.cancel_body(identifiers['dhan'], dry_run=True),
                changes=[
                    self.hash_change('settings', 'dhan', None),
                ],
            ),
            self.cancel(
                'cancel_groww_without_segment',
                self.cancel_body('GMKNOSEGMENT'),
            ),
            self.cancel(
                'cancel_indmoney_derivative_identifier',
                self.cancel_body('DRV-200000001', dry_run=True),
            ),
            self.cancel(
                'cancel_stoxkart_variety_from_data',
                self.cancel_body('SX0002', dry_run=True),
            ),
            self.cancel(
                'cancel_wisdom_capital_identifier_not_numeric',
                self.cancel_body('W-ABC', dry_run=True),
            ),
        ]

    def cancel_broker_scenarios(self):
        """Builds a dry run, a sent cancel and every kind of answer for every broker.

        Returns:
            list: The scenarios.
        """
        scenarios = []
        for broker_name in BROKER_NAMES:
            order_id = OrderRoutesState.ORDER_IDENTIFIERS[broker_name]
            scenarios.append(self.cancel(
                f'cancel_{broker_name}_dry_run',
                self.cancel_body(order_id, dry_run=True),
            ))
            for answer_name, answer in self.answers.cancel_answers(broker_name):
                scenarios.append(self.cancel(
                    f'cancel_{broker_name}_answer_{answer_name}',
                    self.cancel_body(order_id),
                    answer=answer,
                ))
        return scenarios


class OrderRoutesSuite:
    """Runs every scenario against the order blueprint, then records or compares the results.

    Attributes:
        fake_redis (FakeRedis): The stand-in the blueprint under test reads.
        network (FakeBrokerNetwork): The stubbed broker network.
    """

    def __init__(self):
        """Builds the suite with an empty stand-in and a stubbed network.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = FakeRedis()
        self.network = FakeBrokerNetwork()

    def fake_cache(self):
        """Hands the blueprint the stand-in instead of a Redis client.

        Returns:
            FakeRedis: The current stand-in.
        """
        return self.fake_redis

    def fake_mongo_database(self):
        """Hands the blueprint no MongoDB database, since the order routes never read it.

        Returns:
            None: Always None.
        """
        return None

    def fixed_uuid(self):
        """Replaces `uuid.uuid4` so generated identifiers are the same on every run.

        Returns:
            uuid.UUID: A constant identifier.
        """
        return uuid.UUID('00000000-0000-4000-8000-00000000abcd')

    def apply_changes(self, changes):
        """Makes a scenario's edits to the stand-in's contents.

        Args:
            changes (list): Edits built by `OrderRoutesScenarios.string_change` or `hash_change`, where a value of None deletes.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When an edit is of an unknown kind.
        """
        for change in changes:
            value = change['value']
            if change['kind'] == 'string':
                if value is None:
                    self.fake_redis.strings.pop(change['key'], None)
                else:
                    self.fake_redis.strings[change['key']] = value
            elif change['kind'] == 'hash':
                stored_fields = self.fake_redis.hashes.setdefault(
                    change['key'],
                    {},
                )
                if value is None:
                    stored_fields.pop(change['field'], None)
                else:
                    stored_fields[change['field']] = value
            else:
                raise ValueError(f'unknown change kind: {change["kind"]!r}')

    def build_client(self):
        """Builds a Flask test client over a fresh order blueprint.

        Returns:
            flask.testing.FlaskClient: The client.
        """
        application = flask.Flask('order_routes_suite')
        blueprint = orders_blueprint.OrdersBlueprint()
        application.register_blueprint(
            blueprint.blueprint,
            url_prefix='/api/orders',
        )
        return application.test_client()

    def open_request(self, client, request):
        """Sends one scenario request through the test client.

        Args:
            client (flask.testing.FlaskClient): The client over the blueprint under test.
            request (dict): The scenario request.

        Returns:
            werkzeug.test.TestResponse: The response.
        """
        headers = request.get('headers')
        if headers is None:
            headers = {
                'access-token': API_TOKEN,
            }
        if request['route'] == 'place':
            method = 'POST'
            path = '/api/orders/place'
        else:
            method = 'DELETE'
            path = '/api/orders/cancel'
        if 'raw_body' in request:
            return client.open(
                path,
                method=method,
                headers=headers,
                query_string=request.get('query'),
                data=request['raw_body'],
                content_type='application/json',
            )
        if request.get('body') is not None:
            return client.open(
                path,
                method=method,
                headers=headers,
                query_string=request.get('query'),
                json=request['body'],
            )
        return client.open(
            path,
            method=method,
            headers=headers,
            query_string=request.get('query'),
        )

    def send(self, client, request):
        """Prepares the stand-ins for one scenario request, sends it and captures what happened.

        Args:
            client (flask.testing.FlaskClient): The client over the blueprint under test.
            request (dict): The scenario request.

        Returns:
            dict: The status, the response body, the broker requests captured and the Redis round trips made.
        """
        self.apply_changes(request.get('changes', []))
        self.network.reset(request.get('answer'))
        self.fake_redis.round_trips = 0
        self.fake_redis.failing_round_trip = request.get('failing_round_trip')
        if request.get('counter') is not None:
            counter_before = str(request['counter'] - 1)
            counter_key = 'unified:orders:round_robin'
            self.fake_redis.strings[counter_key] = counter_before
        excluded = request.get('excluded')
        if excluded is None:
            excluded = [
                '',
            ]
        api_configuration['order_excluded_brokers'] = excluded

        response = self.open_request(client, request)

        body = response.get_json(silent=True)
        if isinstance(body, dict) and isinstance(body.get('timing_ms'), dict):
            body['timing_ms'] = sorted(body['timing_ms'])
        return {
            'status': response.status_code,
            'body': body,
            'sent': copy.deepcopy(self.network.sent_requests),
            'redis_round_trips': self.fake_redis.round_trips,
        }

    def run_scenario(self, scenario):
        """Runs one scenario from fresh Redis contents and a fresh blueprint.

        Args:
            scenario (dict): The scenario.

        Returns:
            dict: The scenario's recorded result.
        """
        self.fake_redis = OrderRoutesState().build()
        api_configuration['order_broker_selector'] = scenario.get(
            'selector',
            'round_robin',
        )
        priority = scenario.get('priority')
        if priority is None:
            priority = [
                '',
            ]
        api_configuration['order_broker_priority'] = priority
        if scenario.get('expect_construction_error'):
            try:
                self.build_client()
            except ValueError as error:
                return {
                    'name': scenario['name'],
                    'construction_error': str(error),
                }
            return {
                'name': scenario['name'],
                'construction_error': None,
            }
        client = self.build_client()
        if 'steps' not in scenario:
            result = self.send(client, scenario)
            result['name'] = scenario['name']
            return result
        step_results = []
        for step in scenario['steps']:
            step_result = self.send(client, step)
            step_result['step'] = step['name']
            step_results.append(step_result)
        return {
            'name': scenario['name'],
            'steps': step_results,
        }

    def run_every_scenario(self):
        """Runs every scenario with Redis, MongoDB, the broker network and `uuid.uuid4` replaced.

        Returns:
            list: One recorded result per scenario, in order.
        """
        original_get_cache = blueprint_base.get_cache
        original_get_mongo_database = blueprint_base.get_mongo_db
        original_request = requests.Session.request
        original_uuid4 = uuid.uuid4
        original_excluded = api_configuration['order_excluded_brokers']
        original_selector = api_configuration['order_broker_selector']
        original_priority = api_configuration['order_broker_priority']
        blueprint_base.get_cache = self.fake_cache
        blueprint_base.get_mongo_db = self.fake_mongo_database
        requests.Session.request = self.network.request
        uuid.uuid4 = self.fixed_uuid
        try:
            results = []
            for scenario in OrderRoutesScenarios().build():
                results.append(self.run_scenario(scenario))
        finally:
            blueprint_base.get_cache = original_get_cache
            blueprint_base.get_mongo_db = original_get_mongo_database
            requests.Session.request = original_request
            uuid.uuid4 = original_uuid4
            api_configuration['order_excluded_brokers'] = original_excluded
            api_configuration['order_broker_selector'] = original_selector
            api_configuration['order_broker_priority'] = original_priority
        return results

    def encode(self, result):
        """Encodes one result as a single stable line of JSON.

        Args:
            result (dict): The result.

        Returns:
            str: The JSON line, with sorted keys.
        """
        return json.dumps(result, sort_keys=True, ensure_ascii=False)

    def record(self, results):
        """Writes the results to the fixture file, one scenario per line.

        Args:
            results (list): The results.

        Returns:
            int: The exit code, always 0.
        """
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for result in results:
            lines.append(self.encode(result))
        FIXTURE_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f'recorded {len(results)} scenarios to {FIXTURE_PATH}')
        return 0

    def read_recording(self):
        """Reads the fixture file.

        Returns:
            dict: Scenario names to recorded results, in file order.
        """
        recorded = {}
        for line in FIXTURE_PATH.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            recorded_result = json.loads(line)
            recorded[recorded_result['name']] = recorded_result
        return recorded

    def compare(self, results):
        """Compares the results with the fixture file and prints every difference.

        Args:
            results (list): The results.

        Returns:
            int: The exit code: 0 when everything matches, 1 otherwise.
        """
        if not FIXTURE_PATH.exists():
            print(f'no recording at {FIXTURE_PATH}; run with --record first')
            return 1
        recorded = self.read_recording()
        failures = 0
        current_names = set()
        for result in results:
            current_names.add(result['name'])
            expected = recorded.get(result['name'])
            if expected is None:
                failures = failures + 1
                print(f'NEW      {result["name"]}')
                print(f'  now:      {self.encode(result)}')
            elif self.encode(expected) != self.encode(result):
                failures = failures + 1
                print(f'CHANGED  {result["name"]}')
                print(f'  recorded: {self.encode(expected)}')
                print(f'  now:      {self.encode(result)}')
        for name in recorded:
            if name not in current_names:
                failures = failures + 1
                print(f'MISSING  {name}')
        passed = len(results) - failures
        print(f'{passed} of {len(results)} scenarios match the recording, {failures} differ')
        if failures:
            return 1
        return 0

    def run(self):
        """Runs the suite from the command line.

        Returns:
            int: The exit code.
        """
        parser = argparse.ArgumentParser(
            description='Check the order routes against their recorded behaviour.',
        )
        parser.add_argument(
            '--record',
            action='store_true',
            help='rewrite the recording from the current code',
        )
        arguments = parser.parse_args()
        results = self.run_every_scenario()
        if arguments.record:
            return self.record(results)
        return self.compare(results)


if __name__ == '__main__':
    sys.exit(OrderRoutesSuite().run())
