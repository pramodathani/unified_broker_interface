"""Offline check of the instrument routes of `/api/instruments` against a recording of their behaviour.

Runs `/details`, `/additional_details`, `/ltp`, `/ohlc`, `/quote`, `/prices` and `/ticks` in-process through Flask's test client, each by `GET` for one instrument and by `POST` for a list. Redis is replaced by the in-memory stand-in `test_runs/order_routes.py` uses, filled through the mapping cache's own encoders, and the blueprint's mapping cache, catalogue and quote service are built around it. Postgres is replaced by an engine that answers only the tick query and fails on anything else, so a scenario that reached the database unexpectedly shows up as a 500. A broker quote is replaced by a scripted answer per broker, and the clock the quote service reads is fixed.

For each scenario it keeps the HTTP status, the response body, the Redis round trips and the broker quotes asked for, and compares them with `test_runs/fixtures/instrument_routes.jsonl`.

No Redis, database, credentials or network are used, and no request leaves the process. The project's `.env` still has to exist, because importing the blueprint imports `utilities.configurations`.

Typical usage:

    python -m test_runs.instrument_routes
    python -m test_runs.instrument_routes --record
"""

import argparse
import datetime
import decimal
import json
import pathlib
import sys
import threading

import flask

from stock_brokers.instruments.historical.utilities.unified import tables as history_tables
from stock_brokers.instruments.mapping.utilities.cache import MappingCache
from stock_brokers.instruments.mapping.utilities.cache import MappingRedisConnection
from stock_brokers.instruments.mapping.utilities.cache import MappingRedisTier
from stock_brokers.instruments.ticks.utilities.pipeline import TICK_COLUMNS
from test_runs import order_routes
from test_runs import redis_stand_ins
from unified_broker_interface.blueprints import base as blueprint_base
from unified_broker_interface.blueprints import instruments as instruments_blueprint
from unified_broker_interface.utilities.broker_quotes.base import QuoteUnavailable
from unified_broker_interface.utilities.broker_quotes.utilities import service as quote_service
from unified_broker_interface.utilities.instrument_catalogue import InstrumentCatalogue
from unified_broker_interface.utilities.instrument_identity import INDIA
from unified_broker_interface.utilities.instrument_identity import identity_to_json

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent
    / 'fixtures'
    / 'instrument_routes.jsonl'
)
MAPPING_DATE = datetime.date(2026, 9, 15)
NOW = datetime.datetime(2026, 9, 15, 10, 0, tzinfo=INDIA).timestamp()
INSTRUMENT_IDENTIFIERS = {
    'infy': '22222222-2222-5222-8222-000000000001',
    'reliance': '22222222-2222-5222-8222-000000000002',
    'nifty_future': '22222222-2222-5222-8222-000000000003',
    'nifty_option': '22222222-2222-5222-8222-000000000004',
    'unquoted': '22222222-2222-5222-8222-000000000005',
    'unknown': '22222222-2222-5222-8222-000000000099',
}


class FixedClock:
    """A stand-in for the `time` module the quote service reads, always answering the same instant."""

    def time(self):
        """The fixed instant every scenario runs at.

        Returns:
            float: The instant as epoch seconds.
        """
        return NOW


class InstrumentRoutesRedis(redis_stand_ins.FakeRedis):
    """The order routes' stand-in, widened with the commands the instrument routes read with."""

    def pipeline(self, transaction=True):
        """Starts a pipeline that also knows the catalogue's lexical range read.

        Args:
            transaction (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            InstrumentRoutesPipeline: The pipeline.
        """
        del transaction
        return InstrumentRoutesPipeline(self)


class InstrumentRoutesPipeline(redis_stand_ins.FakePipeline):
    """The order routes' pipeline, widened with a lexical range read of a sorted set."""

    def zrangebylex(self, key, minimum, maximum, start=None, num=None):
        """Queues a lexical range read of a sorted set.

        Args:
            key (str): The sorted set key.
            minimum (bytes | str): The lower bound, starting with `[` or `(`.
            maximum (bytes | str): The upper bound, starting with `[` or `(`.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            InstrumentRoutesPipeline: This pipeline.
        """
        self.commands.append((
            'zrangebylex',
            [
                key,
                minimum,
                maximum,
                start,
                num,
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
            elif command_name == 'zrangebylex':
                replies.append(self.fake_redis.run_zrangebylex(*arguments))
            else:
                raise ValueError(f'unsupported stand-in command: {command_name!r}')
        self.commands = []
        return replies


class TickRow:
    """One row the stand-in engine returns, reachable through `_mapping` as a SQLAlchemy row is.

    Attributes:
        _mapping (dict): The row's column names to their values.
    """

    def __init__(self, values):
        """Wraps a dictionary of column values.

        Args:
            values (dict): The column names to their values.

        Returns:
            None: This method returns nothing.
        """
        self._mapping = values


class TickConnection:
    """A stand-in database connection that answers only the tick query.

    Attributes:
        engine (TickEngine): The engine it belongs to, which holds the rows.
    """

    def __init__(self, engine):
        """Builds the connection.

        Args:
            engine (TickEngine): The engine it belongs to.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine

    def execution_options(self, **options):
        """Accepts streaming options and ignores them.

        Args:
            **options: The options, such as `stream_results`.

        Returns:
            TickConnection: This connection.
        """
        del options
        return self

    def __enter__(self):
        """Enters the connection's context.

        Returns:
            TickConnection: This connection.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Leaves the connection's context without suppressing anything.

        Args:
            exception_type (type | None): The exception's class, if one was raised.
            exception (BaseException | None): The exception, if one was raised.
            traceback (types.TracebackType | None): Its traceback, if one was raised.

        Returns:
            bool: Always False, so an exception propagates.
        """
        return False

    def execute(self, statement, parameters):
        """Answers the tick query with the rows held for its instrument and period.

        Args:
            statement (sqlalchemy.sql.elements.TextClause): The statement.
            parameters (dict): Its bound parameters.

        Returns:
            list: The matching rows, oldest first.

        Raises:
            RuntimeError: When the statement is not a tick query.
        """
        sql = str(statement)
        is_tick_query = (
            f'FROM {history_tables.TICKS} ' in sql
            or f'FROM {history_tables.TICKS_ADJUSTED} ' in sql
        )
        if not is_tick_query:
            raise RuntimeError(f'the suite does not answer this statement: {sql}')
        self.engine.statements = self.engine.statements + 1
        if parameters['instrument_id'] == self.engine.failing_instrument:
            raise RuntimeError('stand-in tick query failure')
        rows = []
        for instrument_id, values in self.engine.rows:
            if instrument_id != parameters['instrument_id']:
                continue
            if values['time'] < parameters['start']:
                continue
            if values['time'] >= parameters['end']:
                continue
            rows.append(TickRow(values))
        return rows


class TickEngine:
    """A stand-in SQLAlchemy engine that holds scripted tick rows and refuses every other query.

    Attributes:
        rows (list): `(instrument_id, column values)` pairs, oldest first.
        statements (int): How many tick queries were run.
        failing_instrument (str | None): The instrument whose tick query raises, or None when none does.
    """

    def __init__(self, rows, failing_instrument=None):
        """Builds the engine around its rows.

        Args:
            rows (list): `(instrument_id, column values)` pairs, oldest first.
            failing_instrument (str | None): The instrument whose tick query raises, or None when none does.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows
        self.statements = 0
        self.failing_instrument = failing_instrument

    def connect(self):
        """Opens a connection.

        Returns:
            TickConnection: The connection.
        """
        return TickConnection(self)


class ScriptedBrokers:
    """The brokers' quote answers for one scenario, standing in for `QuoteService._from_broker`.

    Attributes:
        answers (dict): Broker names to a last price, or to the text of the error that broker raises.
        calls (list): `[broker, instrument_id]` pairs, one per quote asked for.
    """

    def __init__(self, answers):
        """Builds the stand-in.

        Args:
            answers (dict): Broker names to a last price, or to the text of the error that broker raises.

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers
        self.calls = []
        self._lock = threading.Lock()

    def from_broker(self, broker, handle, identity, cached, now):
        """Answers one broker quote the way the scenario scripts it.

        Args:
            broker (str): The broker asked.
            handle (dict): The broker's handle on the instrument.
            identity (dict): The instrument's identity.
            cached (dict | None): The cached quote, if any.
            now (float): The instant the request started.

        Returns:
            dict: A quote document in the unified quote shape.

        Raises:
            QuoteUnavailable: When the scenario scripts this broker to fail.
        """
        del handle
        del cached
        with self._lock:
            self.calls.append([
                broker,
                str(identity['instrument_id']),
            ])
        answer = self.answers.get(broker)
        if answer is None or isinstance(answer, str):
            raise QuoteUnavailable(answer or f'{broker} is not scripted')
        document = identity_to_json(identity)
        document.update({
            'last_price': answer,
            'last_trade_time': now - 5,
            'received_at': now,
            'ohlc': {
                'open': answer,
                'high': answer,
                'low': answer,
            },
            'previous_close': answer,
            'change_percent': 0.0,
            'depth': {
                'buy': [],
                'sell': [],
            },
        })
        return document


class InstrumentRoutesState:
    """Builds the Redis contents and tick rows every scenario starts from."""

    def __init__(self):
        """Builds the state builder around the mapping cache's own encoders.

        Returns:
            None: This method returns nothing.
        """
        self.tier = MappingRedisTier(MappingRedisConnection(client=object()))
        self.prefix = f'unified:catalogue:{MAPPING_DATE.isoformat()}:'

    def build(self):
        """Builds a fresh stand-in holding the starting contents.

        Returns:
            InstrumentRoutesRedis: The stand-in.
        """
        fake_redis = InstrumentRoutesRedis()
        fake_redis.strings['unified:catalogue:current_date'] = MAPPING_DATE.isoformat()
        fake_redis.hashes['last_login'] = order_routes.OrderRoutesState().logins()
        self.add_instruments(fake_redis)
        self.add_quotes(fake_redis)
        self.add_candles(fake_redis)
        return fake_redis

    def add_instruments(self, fake_redis):
        """Adds every instrument's identity, catalogue member, seen dates, handles and attributes.

        Args:
            fake_redis (InstrumentRoutesRedis): The stand-in to fill.

        Returns:
            None: This method returns nothing.
        """
        self.add_instrument(
            fake_redis,
            'infy',
            self.security('nse_equities', 'INFY'),
            self.handles(
                [
                    'zerodha',
                    'dhan',
                ],
                '1594',
                '1',
                '0.05',
            ),
            {
                'zerodha': {
                    'isin': 'INE009A01021',
                    'display_name': 'INFOSYS',
                },
                'dhan': {
                    'isin': 'INE009A01021',
                    'series': 'EQ',
                },
            },
        )
        self.add_instrument(
            fake_redis,
            'reliance',
            self.security('nse_equities', 'RELIANCE'),
            self.handles(
                [
                    'zerodha',
                    'dhan',
                ],
                '2885',
                '1',
                '0.10',
            ),
            None,
        )
        self.add_instrument(
            fake_redis,
            'nifty_future',
            self.future('nse_equity_index_futures', 'NIFTY', datetime.date(2026, 10, 27)),
            self.handles(
                [
                    'zerodha',
                ],
                '35001',
                '75',
                '0.10',
            ),
            None,
        )
        self.add_instrument(
            fake_redis,
            'nifty_option',
            self.option(
                'nse_equity_index_options',
                'NIFTY',
                datetime.date(2026, 10, 27),
                decimal.Decimal('25000'),
                'CE',
            ),
            self.handles(
                [
                    'zerodha',
                    'dhan',
                ],
                '41234',
                '75',
                '0.05',
            ),
            None,
        )
        self.add_instrument(
            fake_redis,
            'unquoted',
            self.security('nse_equities', 'QUIETCO'),
            self.handles(
                [
                    'groww',
                ],
                '9999',
                '1',
                '0.05',
            ),
            None,
        )
        fake_redis.hashes[self.prefix + 'segments'] = {
            'nse_equities': '3',
            'nse_equity_index_futures': '1',
            'nse_equity_index_options': '1',
        }

    def add_instrument(self, fake_redis, name, identity, handles, attributes):
        """Adds one instrument through the mapping cache's encoders.

        Args:
            fake_redis (InstrumentRoutesRedis): The stand-in to fill.
            name (str): The instrument's key in `INSTRUMENT_IDENTIFIERS`.
            identity (dict): The identity fields other than `instrument_id` and `mapping_date`.
            handles (dict): Broker names to order handles.
            attributes (dict | None): Broker names to additional attributes, or None for none.

        Returns:
            None: This method returns nothing.
        """
        instrument_id = INSTRUMENT_IDENTIFIERS[name]
        full_identity = {
            'instrument_id': instrument_id,
            'exchange': 'nse',
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
        identity_hash = fake_redis.hashes.setdefault(self.prefix + 'identity', {})
        identity_hash[instrument_id] = self.tier.encode_identity(full_identity)
        catalogue_key = self.prefix + 'catalogue:' + full_identity['segment']
        members = fake_redis.sorted_sets.setdefault(catalogue_key, [])
        members.append(self.tier.encode_catalogue_member(full_identity))
        seen_hash = fake_redis.hashes.setdefault(self.prefix + 'seen', {})
        seen_hash[instrument_id] = self.tier.encode_seen(
            datetime.date(2024, 1, 2),
            MAPPING_DATE,
        )
        handles_hash = fake_redis.hashes.setdefault(self.prefix + 'order_handles', {})
        handles_hash[instrument_id] = self.tier.encode_order_handles(handles)
        attributes_hash = fake_redis.hashes.setdefault(self.prefix + 'additional_attributes', {})
        if attributes is not None:
            attributes_hash[instrument_id] = self.tier.encode_additional_attributes(attributes)

    def add_quotes(self, fake_redis):
        """Adds the live quotes: a fresh one for INFY, and an hour old one for RELIANCE and the NIFTY future.

        Args:
            fake_redis (InstrumentRoutesRedis): The stand-in to fill.

        Returns:
            None: This method returns nothing.
        """
        live = fake_redis.hashes.setdefault('unified:quotes:live', {})
        live[INSTRUMENT_IDENTIFIERS['infy']] = self.quote('infy', 1521.4, NOW - 60)
        live[INSTRUMENT_IDENTIFIERS['reliance']] = self.quote('reliance', 2874.05, NOW - 3600)
        live[INSTRUMENT_IDENTIFIERS['nifty_future']] = self.quote('nifty_future', 25310.5, NOW - 3600)

    def quote(self, name, last_price, received_at):
        """Builds one cached quote document as JSON text.

        Args:
            name (str): The instrument's key in `INSTRUMENT_IDENTIFIERS`.
            last_price (float): The last traded price.
            received_at (float): When the quote was received, as epoch seconds.

        Returns:
            str: The quote document as JSON.
        """
        return json.dumps({
            'instrument_id': INSTRUMENT_IDENTIFIERS[name],
            'last_price': last_price,
            'last_trade_time': received_at - 1,
            'received_at': received_at,
            'ohlc': {
                'open': last_price - 10,
                'high': last_price + 5,
                'low': last_price - 12,
            },
            'previous_close': last_price - 8,
            'change_percent': 0.5,
            'depth': {
                'buy': [],
                'sell': [],
            },
            'stale': False,
        })

    def add_candles(self, fake_redis):
        """Adds a cached copy of INFY's adjusted daily candles for the first week of September 2026.

        Args:
            fake_redis (InstrumentRoutesRedis): The stand-in to fill.

        Returns:
            None: This method returns nothing.
        """
        candles = []
        for day in range(1, 8):
            moment = datetime.datetime(2026, 9, day, tzinfo=INDIA)
            candles.append([
                moment.isoformat(),
                1500.0 + day,
                1510.0 + day,
                1490.0 + day,
                1505.0 + day,
                100000 + day,
                None,
                1.0,
            ])
        key = 'unified:prices:cache:' + INSTRUMENT_IDENTIFIERS['infy'] + ':day:adjusted:latest'
        fake_redis.strings[key] = json.dumps({
            'last_run': 'none',
            'built_at': NOW,
            'from': '2026-09-01',
            'to': '2026-09-07',
            'columns': [
                'time',
                'open',
                'high',
                'low',
                'close',
                'volume',
                'oi',
                'price_factor',
            ],
            'candles': candles,
        })

    def tick_rows(self):
        """Builds two ticks for INFY and one for the NIFTY future, all on the mapping date's morning.

        Returns:
            list: `(instrument_id, column values)` pairs, oldest first.
        """
        rows = []
        scripted = [
            (
                'infy',
                datetime.datetime(2026, 9, 15, 9, 15, 1, tzinfo=INDIA),
                1520.0,
            ),
            (
                'nifty_future',
                datetime.datetime(2026, 9, 15, 9, 15, 2, tzinfo=INDIA),
                25300.0,
            ),
            (
                'infy',
                datetime.datetime(2026, 9, 15, 9, 15, 3, tzinfo=INDIA),
                1520.5,
            ),
        ]
        for name, moment, last_price in scripted:
            values = {}
            for column in TICK_COLUMNS:
                values[column] = None
            del values['instrument_id']
            values['time'] = moment
            values['broker'] = 'zerodha'
            values['last_price'] = decimal.Decimal(str(last_price))
            values['volume'] = 1000
            values['bid1_price'] = decimal.Decimal(str(last_price - 0.05))
            values['bid1_quantity'] = 10
            values['bid1_orders'] = 2
            rows.append((INSTRUMENT_IDENTIFIERS[name], values))
        return rows

    def handles(self, brokers, token, lot_size, tick_size):
        """Builds the same order handle for each of several brokers.

        Args:
            brokers (list): The broker names.
            token (str): The broker token every broker shares.
            lot_size (str): The lot size.
            tick_size (str): The tick size.

        Returns:
            dict: Broker names to order handles.
        """
        handles = {}
        for broker in brokers:
            handles[broker] = {
                'broker_token': token,
                'order_symbol': f'{token}-{broker}',
                'lot_size': lot_size,
                'tick_size': tick_size,
            }
        return handles

    def security(self, segment, symbol):
        """Builds the identity fields of a security.

        Args:
            segment (str): The exchange-prefixed segment.
            symbol (str): The symbol.

        Returns:
            dict: The identity fields.
        """
        return {
            'segment': segment,
            'shape': 'security',
            'symbol': symbol,
        }

    def future(self, segment, underlying_symbol, expiry_date):
        """Builds the identity fields of a future.

        Args:
            segment (str): The exchange-prefixed segment.
            underlying_symbol (str): The underlying's symbol.
            expiry_date (datetime.date): The expiry.

        Returns:
            dict: The identity fields.
        """
        return {
            'segment': segment,
            'shape': 'future',
            'underlying_symbol': underlying_symbol,
            'expiry_date': expiry_date,
        }

    def option(self, segment, underlying_symbol, expiry_date, strike_price, option_type):
        """Builds the identity fields of an option.

        Args:
            segment (str): The exchange-prefixed segment.
            underlying_symbol (str): The underlying's symbol.
            expiry_date (datetime.date): The expiry.
            strike_price (decimal.Decimal): The strike.
            option_type (str): `CE` or `PE`.

        Returns:
            dict: The identity fields.
        """
        return {
            'segment': segment,
            'shape': 'option',
            'underlying_symbol': underlying_symbol,
            'expiry_date': expiry_date,
            'strike_price': strike_price,
            'option_type': option_type,
        }


class InstrumentRoutesScenarios:
    """Builds every scenario the suite runs, in the order they are recorded."""

    def build(self):
        """Builds every scenario.

        Returns:
            list: The scenarios, each a dictionary.
        """
        scenarios = []
        scenarios.extend(self.details_scenarios())
        scenarios.extend(self.quote_scenarios())
        scenarios.extend(self.history_scenarios())
        scenarios.extend(self.details_batch_scenarios())
        scenarios.extend(self.quote_batch_scenarios())
        scenarios.extend(self.history_batch_scenarios())
        return scenarios

    def get(self, name, route, query, **settings):
        """Builds one GET scenario.

        Args:
            name (str): The scenario's name.
            route (str): The route under `/api/instruments/`.
            query (dict): The query parameters.
            **settings: Other scenario settings, such as `brokers` or `headers`.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'method': 'GET',
            'route': route,
            'query': query,
        }
        scenario.update(settings)
        return scenario

    def post(self, name, route, body, **settings):
        """Builds one POST scenario.

        Args:
            name (str): The scenario's name.
            route (str): The route under `/api/instruments/`.
            body (Any): The JSON body, or None to send none.
            **settings: Other scenario settings, such as `brokers` or `headers`.

        Returns:
            dict: The scenario.
        """
        scenario = {
            'name': name,
            'method': 'POST',
            'route': route,
            'body': body,
        }
        scenario.update(settings)
        return scenario

    def by_id(self, name):
        """Builds query parameters naming an instrument by id.

        Args:
            name (str): The instrument's key in `INSTRUMENT_IDENTIFIERS`.

        Returns:
            dict: The query parameters.
        """
        return {
            'instrument_id': INSTRUMENT_IDENTIFIERS[name],
        }

    def details_scenarios(self):
        """Builds the `/details` and `/additional_details` scenarios.

        Returns:
            list: The scenarios.
        """
        return [
            self.get('details_by_id', 'details', self.by_id('infy')),
            self.get(
                'details_by_symbol',
                'details',
                {
                    'exchange': 'nse',
                    'segment': 'equities',
                    'symbol': 'infy',
                },
            ),
            self.get(
                'details_future_by_fields',
                'details',
                {
                    'exchange': 'nse',
                    'segment': 'equity_index_futures',
                    'underlying_symbol': 'NIFTY',
                    'expiry_date': '2026-10-27',
                },
            ),
            self.get(
                'details_option_by_fields',
                'details',
                {
                    'exchange': 'nse',
                    'segment': 'equity_index_options',
                    'underlying_symbol': 'NIFTY',
                    'expiry_date': '2026-10-27',
                    'strike_price': '25000',
                    'option_type': 'ce',
                },
            ),
            self.get('details_unknown_id', 'details', self.by_id('unknown')),
            self.get(
                'details_unknown_symbol',
                'details',
                {
                    'exchange': 'nse',
                    'segment': 'equities',
                    'symbol': 'NOSUCHSTOCK',
                },
            ),
            self.get(
                'details_missing_fields',
                'details',
                {
                    'exchange': 'nse',
                    'segment': 'equity_index_futures',
                    'underlying_symbol': 'NIFTY',
                },
            ),
            self.get(
                'details_bad_id',
                'details',
                {
                    'instrument_id': 'not-a-uuid',
                },
            ),
            self.get(
                'details_no_token',
                'details',
                self.by_id('infy'),
                headers={},
            ),
            self.get('additional_details_by_id', 'additional_details', self.by_id('infy')),
            self.get('additional_details_none_published', 'additional_details', self.by_id('reliance')),
        ]

    def quote_scenarios(self):
        """Builds the `/ltp`, `/ohlc` and `/quote` scenarios.

        Returns:
            list: The scenarios.
        """
        brokers = {
            'zerodha': 2875.5,
            'dhan': 2875.0,
        }
        return [
            self.get('ltp_fresh_cache', 'ltp', self.by_id('infy')),
            self.get('ohlc_fresh_cache', 'ohlc', self.by_id('infy')),
            self.get('quote_fresh_cache', 'quote', self.by_id('infy')),
            self.get('ltp_stale_from_broker', 'ltp', self.by_id('reliance'), brokers=brokers),
            self.get(
                'ltp_first_broker_fails',
                'ltp',
                self.by_id('reliance'),
                brokers={
                    'zerodha': 'Kite returned no quote',
                    'dhan': 2875.0,
                },
            ),
            self.get(
                'ltp_every_broker_fails',
                'ltp',
                self.by_id('reliance'),
                brokers={
                    'zerodha': 'Kite returned no quote',
                    'dhan': 'Dhan refused',
                },
            ),
            self.get('ltp_uncached_from_broker', 'ltp', self.by_id('nifty_option'), brokers=brokers),
            self.get('ltp_no_quote_broker', 'ltp', self.by_id('unquoted'), brokers=brokers),
            self.get('ltp_unknown', 'ltp', self.by_id('unknown')),
        ]

    def history_scenarios(self):
        """Builds the `/prices` and `/ticks` scenarios.

        Returns:
            list: The scenarios.
        """
        return [
            self.get(
                'prices_from_cache',
                'prices',
                {
                    'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
                    'interval': 'day',
                    'from': '2026-09-02',
                    'to': '2026-09-04',
                },
            ),
            self.get(
                'prices_missing_interval',
                'prices',
                {
                    'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
                    'from': '2026-09-02',
                    'to': '2026-09-04',
                },
            ),
            self.get(
                'prices_range_and_days',
                'prices',
                {
                    'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
                    'interval': 'day',
                    'from': '2026-09-02',
                    'days': '3',
                },
            ),
            self.get(
                'ticks_two_rows',
                'ticks',
                {
                    'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
                    'start': '2026-09-15T09:15:00+05:30',
                    'end': '2026-09-15T09:16:00+05:30',
                },
            ),
            self.get(
                'ticks_future_as_served',
                'ticks',
                {
                    'exchange': 'nse',
                    'segment': 'equity_index_futures',
                    'underlying_symbol': 'NIFTY',
                    'expiry_date': '2026-10-27',
                    'start': '2026-09-15T09:15:00+05:30',
                    'end': '2026-09-15T09:16:00+05:30',
                },
            ),
            self.get(
                'ticks_end_before_start',
                'ticks',
                {
                    'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
                    'start': '2026-09-15T09:16:00+05:30',
                    'end': '2026-09-15T09:15:00+05:30',
                },
            ),
        ]


    def mixed_instruments(self):
        """Builds a list naming four instruments in every way a batch accepts: by id, by symbol, and by future and option fields, with JSON numbers.

        Returns:
            list: The list's items.
        """
        return [
            self.by_id('infy'),
            {
                'exchange': 'nse',
                'segment': 'equities',
                'symbol': 'RELIANCE',
            },
            {
                'exchange': 'nse',
                'segment': 'equity_index_futures',
                'underlying_symbol': 'NIFTY',
                'expiry_date': '2026-10-27',
            },
            {
                'exchange': 'nse',
                'segment': 'equity_index_options',
                'underlying_symbol': 'NIFTY',
                'expiry_date': '2026-10-27',
                'strike_price': 25000,
                'option_type': 'ce',
            },
        ]

    def failing_instruments(self):
        """Builds a list in which every item but the last fails in a different way.

        Returns:
            list: The list's items.
        """
        return [
            self.by_id('unknown'),
            {
                'exchange': 'nse',
                'segment': 'equities',
                'symbol': 'NOSUCHSTOCK',
            },
            {
                'exchange': 'nse',
                'segment': 'equity_index_futures',
                'underlying_symbol': 'NIFTY',
            },
            'INFY',
            {
                'instrument_id': 'not-a-uuid',
            },
            {
                'exchange': 'nse',
                'segment': 'equities',
                'symbol': [
                    'INFY',
                ],
            },
            self.by_id('infy'),
        ]

    def details_batch_scenarios(self):
        """Builds the batch `/details` and `/additional_details` scenarios, including every way a body is refused.

        Returns:
            list: The scenarios.
        """
        many_instruments = []
        for _ in range(120):
            many_instruments.append(self.by_id('infy'))
        return [
            self.post('details_batch_mixed', 'details', {'instruments': self.mixed_instruments()}),
            self.post(
                'details_batch_one',
                'details',
                {
                    'instruments': [
                        self.by_id('infy'),
                    ],
                },
            ),
            self.post(
                'details_batch_ids_only',
                'details',
                {
                    'instruments': [
                        self.by_id('infy'),
                        self.by_id('reliance'),
                        self.by_id('nifty_future'),
                    ],
                },
            ),
            self.post('details_batch_failures', 'details', {'instruments': self.failing_instruments()}),
            self.post('details_batch_no_body', 'details', None),
            self.post(
                'details_batch_body_not_object',
                'details',
                [
                    self.by_id('infy'),
                ],
            ),
            self.post('details_batch_no_list', 'details', {'date': '2026-09-15'}),
            self.post('details_batch_empty_list', 'details', {'instruments': []}),
            self.post('details_batch_many_instruments', 'details', {'instruments': many_instruments}),
            self.post(
                'details_batch_bad_date',
                'details',
                {
                    'instruments': [
                        self.by_id('infy'),
                    ],
                    'date': 'yesterday',
                },
            ),
            self.post(
                'details_batch_shared_parameter_not_text',
                'details',
                {
                    'instruments': [
                        self.by_id('infy'),
                    ],
                    'date': {
                        'day': 15,
                    },
                },
            ),
            self.post(
                'details_batch_no_token',
                'details',
                {
                    'instruments': [
                        self.by_id('infy'),
                    ],
                },
                headers={},
            ),
            self.post(
                'additional_details_batch',
                'additional_details',
                {
                    'instruments': [
                        self.by_id('infy'),
                        self.by_id('reliance'),
                        self.by_id('unknown'),
                    ],
                },
            ),
        ]

    def quote_batch_scenarios(self):
        """Builds the batch `/ltp`, `/ohlc` and `/quote` scenarios.

        Returns:
            list: The scenarios.
        """
        brokers = {
            'zerodha': 2875.5,
            'dhan': 2875.0,
        }
        every_kind = {
            'instruments': [
                self.by_id('infy'),
                self.by_id('reliance'),
                self.by_id('nifty_option'),
                self.by_id('unquoted'),
                self.by_id('unknown'),
                self.by_id('nifty_future'),
                'INFY',
            ],
        }
        return [
            self.post(
                'ltp_batch_all_cached',
                'ltp',
                {
                    'instruments': [
                        self.by_id('infy'),
                        {
                            'exchange': 'nse',
                            'segment': 'equities',
                            'symbol': 'INFY',
                        },
                    ],
                },
            ),
            self.post('ltp_batch_every_kind', 'ltp', every_kind, brokers=brokers),
            self.post(
                'ltp_batch_first_broker_fails',
                'ltp',
                {
                    'instruments': [
                        self.by_id('reliance'),
                        self.by_id('nifty_option'),
                        self.by_id('nifty_future'),
                    ],
                },
                brokers={
                    'zerodha': 'Kite returned no quote',
                    'dhan': 2875.0,
                },
            ),
            self.post(
                'ohlc_batch',
                'ohlc',
                {
                    'instruments': [
                        self.by_id('infy'),
                        self.by_id('reliance'),
                    ],
                },
                brokers=brokers,
            ),
            self.post(
                'quote_batch',
                'quote',
                {
                    'instruments': [
                        self.by_id('infy'),
                        self.by_id('reliance'),
                    ],
                },
                brokers=brokers,
            ),
        ]

    def history_batch_scenarios(self):
        """Builds the batch `/prices` and `/ticks` scenarios.

        Returns:
            list: The scenarios.
        """
        infy_twice = [
            self.by_id('infy'),
            {
                'exchange': 'nse',
                'segment': 'equities',
                'symbol': 'INFY',
            },
            'INFY',
        ]
        infy_and_future = [
            self.by_id('infy'),
            {
                'exchange': 'nse',
                'segment': 'equity_index_futures',
                'underlying_symbol': 'NIFTY',
                'expiry_date': '2026-10-27',
            },
            'INFY',
        ]
        return [
            self.post(
                'prices_batch_from_cache',
                'prices',
                {
                    'instruments': infy_twice,
                    'interval': 'day',
                    'from': '2026-09-02',
                    'to': '2026-09-04',
                },
            ),
            self.post(
                'prices_batch_missing_interval',
                'prices',
                {
                    'instruments': infy_twice,
                    'from': '2026-09-02',
                    'to': '2026-09-04',
                },
            ),
            self.post(
                'prices_batch_unknown_interval',
                'prices',
                {
                    'instruments': infy_twice,
                    'interval': 'week',
                    'from': '2026-09-02',
                    'to': '2026-09-04',
                },
            ),
            self.post(
                'prices_batch_to_before_from',
                'prices',
                {
                    'instruments': infy_twice,
                    'interval': 'day',
                    'from': '2026-09-04',
                    'to': '2026-09-02',
                },
            ),
            self.post(
                'ticks_batch',
                'ticks',
                {
                    'instruments': infy_and_future,
                    'start': '2026-09-15T09:15:00+05:30',
                    'end': '2026-09-15T09:16:00+05:30',
                },
            ),
            self.post(
                'ticks_batch_query_fails_part_way',
                'ticks',
                {
                    'instruments': [
                        self.by_id('infy'),
                        self.by_id('nifty_future'),
                        self.by_id('infy'),
                    ],
                    'start': '2026-09-15T09:15:00+05:30',
                    'end': '2026-09-15T09:16:00+05:30',
                },
                failing_tick_query='nifty_future',
            ),
            self.post(
                'ticks_batch_unadjusted',
                'ticks',
                {
                    'instruments': [
                        self.by_id('infy'),
                    ],
                    'start': '2026-09-15T09:15:00+05:30',
                    'end': '2026-09-15T09:16:00+05:30',
                    'adjusted': False,
                },
            ),
            self.post(
                'ticks_batch_end_before_start',
                'ticks',
                {
                    'instruments': infy_and_future,
                    'start': '2026-09-15T09:16:00+05:30',
                    'end': '2026-09-15T09:15:00+05:30',
                },
            ),
        ]


class InstrumentRoutesSuite:
    """Runs the scenarios against a fresh blueprint each time and compares the results with the recording.

    Attributes:
        fake_redis (InstrumentRoutesRedis | None): The stand-in the running scenario reads.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = None

    def fake_cache(self):
        """Stands in for `get_cache`, answering the running scenario's stand-in.

        Returns:
            InstrumentRoutesRedis: The stand-in.
        """
        return self.fake_redis

    def fake_mongo_database(self):
        """Stands in for `get_mongo_db`; the instrument routes never read MongoDB.

        Returns:
            None: Always None.
        """
        return None

    def build_client(self, engine, brokers):
        """Builds a Flask test client over a fresh blueprint whose services read the stand-ins.

        Args:
            engine (TickEngine): The stand-in database engine.
            brokers (ScriptedBrokers): The scripted broker quotes.

        Returns:
            flask.testing.FlaskClient: The client.
        """
        application = flask.Flask('instrument_routes_suite')
        blueprint = instruments_blueprint.InstrumentsBlueprint()
        mapping_cache = MappingCache(
            engine=engine,
            redis_connection=MappingRedisConnection(client=self.fake_redis),
        )
        quotes = quote_service.QuoteService(mapping_cache, self.fake_redis)
        quotes._from_broker = brokers.from_broker
        blueprint._mapping_cache = mapping_cache
        blueprint._catalogue = InstrumentCatalogue(mapping_cache)
        blueprint._quotes = quotes
        application.register_blueprint(
            blueprint.blueprint,
            url_prefix='/api/instruments',
        )
        return application.test_client()

    def run_scenario(self, scenario):
        """Runs one scenario and captures what happened.

        Args:
            scenario (dict): The scenario.

        Returns:
            dict: The name, status, response body, Redis round trips, broker quotes asked for and tick queries run.
        """
        self.fake_redis = InstrumentRoutesState().build()
        failing_instrument = None
        if scenario.get('failing_tick_query') is not None:
            failing_instrument = INSTRUMENT_IDENTIFIERS[scenario['failing_tick_query']]
        engine = TickEngine(InstrumentRoutesState().tick_rows(), failing_instrument)
        brokers = ScriptedBrokers(scenario.get('brokers', {}))
        client = self.build_client(engine, brokers)
        headers = scenario.get('headers')
        if headers is None:
            headers = {
                'access-token': order_routes.API_TOKEN,
            }
        self.fake_redis.round_trips = 0
        path = '/api/instruments/' + scenario['route']
        if scenario['method'] == 'GET':
            response = client.get(path, headers=headers, query_string=scenario['query'])
        else:
            response = client.post(path, headers=headers, json=scenario.get('body'))
        text = response.get_data(as_text=True)
        try:
            body = json.loads(text)
        except ValueError:
            body = text
        result = {
            'name': scenario['name'],
            'status': response.status_code,
            'body': body,
            'redis_round_trips': self.fake_redis.round_trips,
            'broker_calls': sorted(brokers.calls),
            'tick_queries': engine.statements,
        }
        instrument_header = response.headers.get('X-Instrument-Id')
        if instrument_header is not None:
            result['headers'] = {
                'X-Instrument-Id': instrument_header,
                'X-Adjustable': response.headers.get('X-Adjustable'),
                'X-Price-Basis': response.headers.get('X-Price-Basis'),
                'X-Start': response.headers.get('X-Start'),
                'X-End': response.headers.get('X-End'),
            }
        return result

    def run_every_scenario(self):
        """Runs every scenario with Redis, MongoDB and the quote service's clock replaced.

        Returns:
            list: One recorded result per scenario, in order.
        """
        original_get_cache = blueprint_base.get_cache
        original_get_mongo_database = blueprint_base.get_mongo_db
        original_clock = quote_service.time
        blueprint_base.get_cache = self.fake_cache
        blueprint_base.get_mongo_db = self.fake_mongo_database
        quote_service.time = FixedClock()
        try:
            results = []
            for scenario in InstrumentRoutesScenarios().build():
                results.append(self.run_scenario(scenario))
        finally:
            blueprint_base.get_cache = original_get_cache
            blueprint_base.get_mongo_db = original_get_mongo_database
            quote_service.time = original_clock
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
            description='Check the instrument routes against their recorded behaviour.',
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
    sys.exit(InstrumentRoutesSuite().run())
