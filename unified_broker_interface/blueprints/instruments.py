"""
`/api/instruments`: the unified instrument universe, live quotes and stored history.

| Route | Answers from |
| --- | --- |
| `/segments`, `/master`, `/search`, `/details`, `/additional_details` | The Redis instrument mapping cache |
| `/ltp`, `/ohlc`, `/quote` | The unified quote cache, or a broker's REST API when that is not recent enough |
| `/prices` | The Redis copy of the series, or unified.price_history, adjusted on read for equities, ETFs and investment trusts |
| `/ticks` | unified.ticks, likewise, streamed |

Every route except the first three takes one instrument by `GET`, as `instrument_id` or as `exchange`,
`segment` and the identity fields; see `utilities/instrument_identity.py`. The same routes take a list of
any number of instruments by `POST`, as a JSON body `{"instruments": [...]}`, and answer `{"results": [...]}`
with one entry per instrument; see `utilities/instrument_batch.py`. The routes only read parameters and
shape responses - the work is in `utilities/`.
"""

import functools
import threading
from datetime import date, timedelta

from flask import jsonify, request

from stock_brokers.instruments.mapping.utilities.cache import MappingCache
from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated
from unified_broker_interface.utilities import instrument_history
from unified_broker_interface.utilities.broker_quotes.utilities.service import QuoteService
from unified_broker_interface.utilities.instrument_batch import InstrumentBatch
from unified_broker_interface.utilities.instrument_catalogue import InstrumentCatalogue
from unified_broker_interface.utilities.instrument_identity import (RequestError, identity_to_json, parse_bool,
                                                                    parse_date, parse_datetime, parse_exchange,
                                                                    parse_instrument, parse_int, parse_segment)
from unified_broker_interface.utilities.json_stream import json_array_response, json_results_response

SEARCH_LIMIT_DEFAULT = 50
SEARCH_LIMIT_MAXIMUM = 200

_IDENTITY_KEYS = ("instrument_id", "exchange", "segment", "shape", "symbol", "underlying_symbol", "expiry_date",
                  "strike_price", "option_type")
_LTP_KEYS = _IDENTITY_KEYS + ("last_price", "last_trade_time", "received_at", "source")

def answers_request_errors(handler):
    """
    Turn a `RequestError` raised while handling a request into its JSON error and status.

    - `handler` is a blueprint handler method.
    """
    @functools.wraps(handler)
    def wrapper(self, *args, **kwargs):
        try:
            return handler(self, *args, **kwargs)
        except RequestError as error:
            return jsonify({'error': error.message}), error.status
    return wrapper

class InstrumentsBlueprint(BaseBlueprint):
    name = 'instruments'
    routes = [
        ('/segments', 'segments', ['GET']),
        ('/master', 'master', ['GET']),
        ('/search', 'search', ['GET']),
        ('/details', 'details', ['GET', 'POST']),
        ('/additional_details', 'additional_details', ['GET', 'POST']),
        ('/ltp', 'ltp', ['GET', 'POST']),
        ('/ohlc', 'ohlc', ['GET', 'POST']),
        ('/quote', 'quote', ['GET', 'POST']),
        ('/prices', 'prices', ['GET', 'POST']),
        ('/ticks', 'ticks', ['GET', 'POST']),
    ]

    def __init__(self):
        """
        Build the blueprint and its routes, leaving the mapping cache, catalogue and quote service to be built on first use.

        The three services start as None and are built by `_services` under a lock, so importing the module does not touch PostgreSQL.
        """
        super().__init__()
        self._services_lock = threading.Lock()
        self._mapping_cache = None
        self._catalogue = None
        self._quotes = None

    def _services(self):
        """
        This worker's mapping cache, catalogue and quote service, built on first use.

        Built lazily rather than at import, so the application starts without touching Postgres, and
        once per worker, because the mapping cache's in-process tier is only useful when shared.
        """
        with self._services_lock:
            if self._mapping_cache is None:
                self._mapping_cache = MappingCache()
                self._catalogue = InstrumentCatalogue(self._mapping_cache)
                self._quotes = QuoteService(self._mapping_cache, self.cache)
        return self._catalogue, self._quotes

    @authenticated
    @answers_request_errors
    def segments(self):
        """
        Every segment mapped on the current date, with its shape, identity fields and instrument count.
        """
        catalogue, _ = self._services()
        return jsonify(catalogue.segments()), 200

    @authenticated
    @answers_request_errors
    def master(self):
        """
        Every instrument in an exchange and segment, either of which may be `all`, streamed as a JSON array.
        """
        catalogue, _ = self._services()
        exchange = parse_exchange(request.args.get('exchange'), allow_all=True)
        exchange, segment = parse_segment(exchange, request.args.get('segment'), allow_all=True)
        mapping_date, instruments = catalogue.master(exchange, segment, parse_date(request.args.get('date'), 'date'))
        return json_array_response(instruments, headers={'X-Mapping-Date': mapping_date.isoformat()})

    @authenticated
    @answers_request_errors
    def search(self):
        """
        Instruments in one segment whose symbol or underlying contains `q`.
        """
        catalogue, _ = self._services()
        exchange = parse_exchange(request.args.get('exchange'))
        exchange, segment = parse_segment(exchange, request.args.get('segment'))
        limit = parse_int(request.args.get('limit'), 'limit', SEARCH_LIMIT_DEFAULT, 1, SEARCH_LIMIT_MAXIMUM)
        answer = catalogue.search(exchange, segment, request.args.get('q'), parse_date(request.args.get('date'), 'date'),
                                  limit)
        return jsonify(answer), 200

    @authenticated
    @answers_request_errors
    def details(self):
        """
        One instrument's identity, seen dates and every broker's handle.
        """
        if request.method == 'POST':
            return self._details_batch()
        catalogue, _ = self._services()
        answer = catalogue.details(parse_instrument(request.args), parse_date(request.args.get('date'), 'date'))
        return jsonify(answer), 200

    def _details_batch(self):
        """
        The details of each instrument a posted list names.

        Returns:
            tuple: The JSON response `{"results": [...]}` and the status 200.

        Raises:
            RequestError: When the body or the shared `date` cannot be read.
        """
        catalogue, _ = self._services()
        batch = InstrumentBatch(request.get_json(silent=True))
        as_of = parse_date(batch.parameters.get('date'), 'date')
        answers = catalogue.details_many(batch.valid_instruments(), as_of)
        return jsonify({'results': batch.results(answers)}), 200

    @authenticated
    @answers_request_errors
    def additional_details(self):
        """
        One instrument's identity and the extra attributes each broker's own instrument file carries.
        """
        if request.method == 'POST':
            return self._additional_details_batch()
        catalogue, _ = self._services()
        answer = catalogue.additional_details(parse_instrument(request.args),
                                              parse_date(request.args.get('date'), 'date'))
        return jsonify(answer), 200

    def _additional_details_batch(self):
        """
        The additional attributes of each instrument a posted list names.

        Returns:
            tuple: The JSON response `{"results": [...]}` and the status 200.

        Raises:
            RequestError: When the body or the shared `date` cannot be read.
        """
        catalogue, _ = self._services()
        batch = InstrumentBatch(request.get_json(silent=True))
        as_of = parse_date(batch.parameters.get('date'), 'date')
        answers = catalogue.additional_details_many(batch.valid_instruments(), as_of)
        return jsonify({'results': batch.results(answers)}), 200

    def _live_quote(self):
        """
        The requested instrument's quote document, from the cache or a broker.
        """
        catalogue, quotes = self._services()
        identity, mapping_date, _ = catalogue.resolve(parse_instrument(request.args))
        return quotes.quote(identity, mapping_date)

    def _live_quotes_batch(self, narrow):
        """
        The quote of each instrument a posted list names, narrowed by a method of this blueprint.

        Args:
            narrow (Callable[[dict], dict] | None): The method that turns a whole quote document into the route's answer, or None for the whole document.

        Returns:
            tuple: The JSON response `{"results": [...]}` and the status 200.

        Raises:
            RequestError: When the body cannot be read, or nothing has been mapped yet.
        """
        catalogue, quotes = self._services()
        batch = InstrumentBatch(request.get_json(silent=True))
        mapping_date, resolutions = catalogue.resolve_many(batch.valid_instruments())
        identities = []
        for resolution in resolutions:
            if not isinstance(resolution, RequestError):
                identity, _ = resolution
                identities.append(identity)
        documents = quotes.quotes(identities, mapping_date)

        answers = []
        document_position = 0
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                answers.append(resolution)
                continue
            document = documents[document_position]
            document_position = document_position + 1
            if narrow is not None and not isinstance(document, RequestError):
                document = narrow(document)
            answers.append(document)
        return jsonify({'results': batch.results(answers)}), 200

    @authenticated
    @answers_request_errors
    def ltp(self):
        """
        The last traded price.
        """
        if request.method == 'POST':
            return self._live_quotes_batch(self._ltp_values)
        return jsonify(self._ltp_values(self._live_quote())), 200

    @staticmethod
    def _ltp_values(document):
        """
        The identity, last price and timestamps of a quote document.

        Args:
            document (dict): A whole unified quote document.

        Returns:
            dict: The document narrowed to the keys in `_LTP_KEYS`.
        """
        return {key: document.get(key) for key in _LTP_KEYS}

    @authenticated
    @answers_request_errors
    def ohlc(self):
        """
        The day's open, high, low, close and volume, and nothing else.
        """
        if request.method == 'POST':
            return self._live_quotes_batch(self._ohlcv_values)
        return jsonify(self._ohlcv_values(self._live_quote())), 200

    @staticmethod
    def _ohlcv_values(document):
        """
        The day's open, high, low, close and volume from a quote document.

        The quote document has no close of its own, so `close` is the last traded price, which is the day's close once the market has shut.

        Args:
            document (dict): A whole unified quote document.

        Returns:
            dict: `open`, `high`, `low`, `close` and `volume`, each a number or None.
        """
        day_prices = document.get('ohlc') or {}
        return {
            'open': day_prices.get('open'),
            'high': day_prices.get('high'),
            'low': day_prices.get('low'),
            'close': document.get('last_price'),
            'volume': document.get('volume'),
        }

    @authenticated
    @answers_request_errors
    def quote(self):
        """
        The full unified quote document, market depth included.
        """
        if request.method == 'POST':
            return self._live_quotes_batch(None)
        return jsonify(self._live_quote()), 200

    def _price_request(self, parameters):
        """
        The candle parameters of a request, shared by the `GET` form and a posted list.

        Args:
            parameters (Mapping): The request's parameters as text: its query string, or a batch's shared parameters.

        Returns:
            tuple: `(interval, from_date, to_date, adjusted, known_as_of)`, where interval is a str, the dates are datetime.date, adjusted is a bool and known_as_of is a datetime.date or None.

        Raises:
            RequestError: When the interval is missing or unknown, the range is given both ways or neither way, or the range cannot be answered.
        """
        interval = parameters.get('interval')
        if not interval:
            raise RequestError("interval is required")

        days = parse_int(parameters.get('days'), 'days', None, 1, 36500)
        from_date = parse_date(parameters.get('from'), 'from')
        to_date = parse_date(parameters.get('to'), 'to')
        if days is not None:
            if from_date or to_date:
                raise RequestError("give either from and to, or days")
            to_date = date.today()
            from_date = to_date - timedelta(days=days)
        elif from_date is None or to_date is None:
            raise RequestError("from and to are required, or days")

        adjusted = parse_bool(parameters.get('adjusted'), 'adjusted', True)
        known_as_of = parse_date(parameters.get('known_as_of'), 'known_as_of')
        return interval, from_date, to_date, adjusted, known_as_of

    @authenticated
    @answers_request_errors
    def prices(self):
        """
        Candles between two dates, or for the last `days` days.

        Answered from the Redis copy of the series when it covers the range, and from the database
        otherwise; `source` in the answer says which.
        """
        if request.method == 'POST':
            return self._prices_batch()
        catalogue, _ = self._services()
        instrument = parse_instrument(request.args)
        interval, from_date, to_date, adjusted, known_as_of = self._price_request(request.args)
        identity, _, _ = catalogue.resolve(instrument, mapped_only=False)
        answer = instrument_history.candles(
            catalogue.engine, self.cache, identity, interval, from_date, to_date, adjusted, known_as_of)
        return jsonify(answer), 200

    def _prices_batch(self):
        """
        The candles of each instrument a posted list names, over one shared interval and range.

        Returns:
            tuple: The JSON response `{"results": [...]}` and the status 200.

        Raises:
            RequestError: When the body or a shared parameter cannot be read, or the range cannot be answered.
        """
        catalogue, _ = self._services()
        batch = InstrumentBatch(request.get_json(silent=True))
        interval, from_date, to_date, adjusted, known_as_of = self._price_request(batch.parameters)
        instrument_history.check_candle_range(interval, from_date, to_date)
        _, resolutions = catalogue.resolve_many(batch.valid_instruments(), mapped_only=False)
        answers = []
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                answers.append(resolution)
                continue
            identity, _ = resolution
            answers.append(instrument_history.candles(
                catalogue.engine, self.cache, identity, interval, from_date, to_date, adjusted, known_as_of))
        return jsonify({'results': batch.results(answers)}), 200

    @authenticated
    @answers_request_errors
    def ticks(self):
        """
        Every stored tick between `start` and `end`, streamed as a JSON array.
        """
        if request.method == 'POST':
            return self._ticks_batch()
        catalogue, _ = self._services()
        instrument = parse_instrument(request.args)
        start = parse_datetime(request.args.get('start'), 'start')
        end = parse_datetime(request.args.get('end'), 'end')
        adjusted = parse_bool(request.args.get('adjusted'), 'adjusted', True)
        identity, _, _ = catalogue.resolve(instrument, mapped_only=False)
        headers, rows = instrument_history.tick_stream(catalogue.engine, identity, start, end, adjusted)
        return json_array_response(rows, headers=headers)

    def _ticks_batch(self):
        """
        The ticks of each instrument a posted list names, over one shared period, streamed instrument by instrument.

        Every instrument is resolved before the stream starts, so an unknown one is an entry with its own status; each instrument's ticks are then read from the database as the stream reaches its entry.

        Returns:
            flask.Response: The streaming response `{"results": [...]}`, each answered entry carrying its rows under `ticks`.

        Raises:
            RequestError: When the body or a shared parameter cannot be read, or the period ends before it starts.
        """
        catalogue, _ = self._services()
        batch = InstrumentBatch(request.get_json(silent=True))
        start = parse_datetime(batch.parameters.get('start'), 'start')
        end = parse_datetime(batch.parameters.get('end'), 'end')
        adjusted = parse_bool(batch.parameters.get('adjusted'), 'adjusted', True)
        instrument_history.check_tick_period(start, end)
        _, resolutions = catalogue.resolve_many(batch.valid_instruments(), mapped_only=False)

        answers = []
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                answers.append(resolution)
                continue
            identity, _ = resolution
            series = instrument_history.tick_series(identity, start, end, adjusted)
            answers.append({**identity_to_json(identity), **series})
        entries = batch.results(answers)

        def entries_with_rows():
            for entry in entries:
                if entry['status'] != 200:
                    yield entry, None
                    continue
                series = entry['data']
                rows = instrument_history.tick_documents(catalogue.engine, series['instrument_id'],
                                                         series['price_basis'], start, end)
                yield entry, rows

        return json_results_response(entries_with_rows(), 'ticks')

instruments_bp = InstrumentsBlueprint().blueprint
