"""
`/api/instruments`: the unified instrument universe, live quotes and stored history.

| Route | Answers from |
| --- | --- |
| `/segments`, `/master`, `/search`, `/details` | The Redis instrument mapping cache |
| `/ltp`, `/ohlc`, `/quote` | The unified quote cache, or a broker's REST API when that is not recent enough |
| `/prices` | unified.price_history, adjusted on read for equities, ETFs and investment trusts |
| `/ticks` | unified.ticks, likewise, streamed |

Every route except the first three takes one instrument, as `instrument_id` or as `exchange`, `segment`
and the identity fields; see `utilities/instrument_identity.py`. The routes only read parameters and
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
from unified_broker_interface.utilities.instrument_catalogue import InstrumentCatalogue
from unified_broker_interface.utilities.instrument_identity import (RequestError, parse_bool, parse_date,
                                                                    parse_datetime, parse_exchange, parse_instrument,
                                                                    parse_int, parse_segment)
from unified_broker_interface.utilities.json_stream import json_array_response

SEARCH_LIMIT_DEFAULT = 50
SEARCH_LIMIT_MAXIMUM = 200

_IDENTITY_KEYS = ("instrument_id", "exchange", "segment", "shape", "symbol", "underlying_symbol", "expiry_date",
                  "strike_price", "option_type")
_LTP_KEYS = _IDENTITY_KEYS + ("last_price", "last_trade_time", "received_at", "source")
_OHLC_KEYS = _LTP_KEYS + ("ohlc", "previous_close", "change_percent")

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
        ('/details', 'details', ['GET']),
        ('/ltp', 'ltp', ['GET']),
        ('/ohlc', 'ohlc', ['GET']),
        ('/quote', 'quote', ['GET']),
        ('/prices', 'prices', ['GET']),
        ('/ticks', 'ticks', ['GET']),
    ]

    def __init__(self):
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
        catalogue, _ = self._services()
        answer = catalogue.details(parse_instrument(request.args), parse_date(request.args.get('date'), 'date'))
        return jsonify(answer), 200

    def _live_quote(self):
        """
        The requested instrument's quote document, from the cache or a broker.
        """
        catalogue, quotes = self._services()
        identity, mapping_date, _ = catalogue.resolve(parse_instrument(request.args))
        return quotes.quote(identity, mapping_date)

    @authenticated
    @answers_request_errors
    def ltp(self):
        """
        The last traded price.
        """
        document = self._live_quote()
        return jsonify({key: document.get(key) for key in _LTP_KEYS}), 200

    @authenticated
    @answers_request_errors
    def ohlc(self):
        """
        The last price with the day's open, high and low, and the previous close.
        """
        document = self._live_quote()
        return jsonify({key: document.get(key) for key in _OHLC_KEYS}), 200

    @authenticated
    @answers_request_errors
    def quote(self):
        """
        The full unified quote document, market depth included.
        """
        return jsonify(self._live_quote()), 200

    @authenticated
    @answers_request_errors
    def prices(self):
        """
        Candles between two dates, or for the last `days` days.
        """
        catalogue, _ = self._services()
        instrument = parse_instrument(request.args)
        interval = request.args.get('interval')
        if not interval:
            raise RequestError("interval is required")

        days = parse_int(request.args.get('days'), 'days', None, 1, 36500)
        from_date = parse_date(request.args.get('from'), 'from')
        to_date = parse_date(request.args.get('to'), 'to')
        if days is not None:
            if from_date or to_date:
                raise RequestError("give either from and to, or days")
            to_date = date.today()
            from_date = to_date - timedelta(days=days)
        elif from_date is None or to_date is None:
            raise RequestError("from and to are required, or days")

        identity, _, _ = catalogue.resolve(instrument, mapped_only=False)
        answer = instrument_history.candles(
            catalogue.engine, identity, interval, from_date, to_date,
            parse_bool(request.args.get('adjusted'), 'adjusted', True),
            parse_date(request.args.get('known_as_of'), 'known_as_of'))
        return jsonify(answer), 200

    @authenticated
    @answers_request_errors
    def ticks(self):
        """
        Every stored tick between `start` and `end`, streamed as a JSON array.
        """
        catalogue, _ = self._services()
        instrument = parse_instrument(request.args)
        start = parse_datetime(request.args.get('start'), 'start')
        end = parse_datetime(request.args.get('end'), 'end')
        adjusted = parse_bool(request.args.get('adjusted'), 'adjusted', True)
        identity, _, _ = catalogue.resolve(instrument, mapped_only=False)
        headers, rows = instrument_history.tick_stream(catalogue.engine, identity, start, end, adjusted)
        return json_array_response(rows, headers=headers)

instruments_bp = InstrumentsBlueprint().blueprint
