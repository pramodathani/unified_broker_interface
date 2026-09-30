"""Finds instruments with `/api/instruments`: the segments, a segment's listing, a search, and one instrument's details.

These routes answer from the instrument catalogue the daily mapping job writes into Redis, so they ask no broker. `segments` lists every segment mapped on the current date with its instrument count, `master` streams every instrument of a scope, `search` finds names containing a term, `details` answers one instrument's identity, the dates it was seen and each broker's handle, and `additional_details` adds the extra attributes each broker's own file carries. `details` and `additional_details` also take a list of instruments by POST and answer each on its own.

This program fills an in-memory Redis stand-in with the small catalogue the offline instrument route suite uses, from `test_runs/instrument_routes.py`, and calls each handler inside a Flask request context. The blueprint's mapping cache, catalogue and quote service are pointed at the stand-in before the first request, which is the one step the program does differently from a real worker.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/instruments/InstrumentsBlueprint/example_1_finding_instruments.py
"""

import datetime
import json

import flask

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingCache,
    MappingRedisConnection,
)
from test_runs.instrument_routes import (
    INSTRUMENT_IDENTIFIERS,
    InstrumentRoutesRedis,
    InstrumentRoutesState,
    TickEngine,
)
from unified_broker_interface.blueprints.instruments import (
    InstrumentsBlueprint,
)
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.utilities import service as quote_service
from unified_broker_interface.utilities.instrument_catalogue import (
    InstrumentCatalogue,
)
from unified_broker_interface.utilities.instrument_identity import (
    INDIA,
    identity_to_json,
)
from unified_broker_interface.utilities.tokens import (
    TokenStore,
)

ACCESS_TOKEN = 'api-token'
NOW = datetime.datetime(2026, 9, 15, 10, 0, tzinfo=INDIA)


class CatalogueRedis(InstrumentRoutesRedis):
    """The instrument route suite's in-memory Redis stand-in, widened with the index range read that listings and searches use."""

    def zrange(self, key, start, stop):
        """Reads members of a sorted set by position, in lexical order since every member scores 0.

        Args:
            key (str): The sorted set key.
            start (int): The first position.
            stop (int): The last position, inclusive, where -1 means the end.

        Returns:
            list: The members.
        """
        self.start_round_trip()
        members = sorted(self.sorted_sets.get(key, []))
        if stop == -1:
            return members[start:]
        return members[start:stop + 1]


class FixedClock:
    """A stand-in for the `time` module the quote service reads, fixed at 10:00 IST on 15 September 2026."""

    def time(self):
        """The fixed instant.

        Returns:
            float: The instant as epoch seconds.
        """
        return NOW.timestamp()


class ScriptedBrokerQuotes:
    """Stands in for asking a broker's REST API for a quote, answering each broker with a fixed last price.

    Attributes:
        last_prices (dict): Broker names to the last price that broker answers with; a broker not named fails.
        asked (list): The brokers asked, in order.
    """

    def __init__(self, last_prices):
        """Builds the stand-in.

        Args:
            last_prices (dict): Broker names to the last price that broker answers with.

        Returns:
            None: This method returns nothing.
        """
        self.last_prices = last_prices
        self.asked = []

    def quote_from(self, broker, handle, identity, cached, now):
        """Answers one broker quote in the unified quote shape.

        Args:
            broker (str): The broker asked.
            handle (dict): The broker's handle on the instrument.
            identity (dict): The instrument's identity.
            cached (dict | None): The cached quote, if any.
            now (float): The instant the request started, as epoch seconds.

        Returns:
            dict: The quote document.

        Raises:
            QuoteUnavailable: When the broker is not given a price.
        """
        del handle
        del cached
        self.asked.append(broker)
        if broker not in self.last_prices:
            raise QuoteUnavailable(f'{broker} has no quote in this example')
        last_price = self.last_prices[broker]
        document = identity_to_json(identity)
        document.update({
            'last_price': last_price,
            'last_trade_time': now - 2,
            'received_at': now,
            'ohlc': {
                'open': last_price - 20,
                'high': last_price + 5,
                'low': last_price - 25,
            },
            'previous_close': last_price - 10,
            'change_percent': 0.35,
            'depth': {
                'buy': [],
                'sell': [],
            },
        })
        return document


LAST_PRICES = {}


class FindingInstrumentsExample:
    """Calls the catalogue routes and prints a short line for each answer.

    Attributes:
        cache (CatalogueRedis): The stand-in Redis client, holding the catalogue of 15 September 2026, live quotes and cached candles.
        engine (TickEngine): The stand-in database engine, which answers only tick queries.
        brokers (ScriptedBrokerQuotes): The stand-in for asking a broker for a quote.
        blueprint (InstrumentsBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
    """

    def __init__(self):
        """Builds the blueprint over the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.cache = None
        self.engine = None
        self.brokers = None
        self.blueprint = None
        self.application = None
        self.build_blueprint(LAST_PRICES)

    def build_blueprint(self, last_prices):
        """Builds the blueprint and points its mapping cache, catalogue and quote service at the stand-ins.

        The blueprint normally builds these three on first use, reading the real Redis and PostgreSQL; setting them beforehand is how the route suite runs it offline too.

        Args:
            last_prices (dict): Broker names to the last price each answers a quote with.

        Returns:
            None: This method returns nothing.
        """
        state = InstrumentRoutesState()
        filled = state.build()
        self.cache = CatalogueRedis()
        self.cache.strings = filled.strings
        self.cache.hashes = filled.hashes
        self.cache.sorted_sets = filled.sorted_sets
        for segment, names in [
            (
                'nse_equities',
                [
                    'INFY',
                    'QUIETCO',
                    'RELIANCE',
                ],
            ),
            (
                'nse_equity_index_futures',
                [
                    'NIFTY',
                ],
            ),
        ]:
            self.cache.sorted_sets[state.prefix + 'names:' + segment] = names
        self.engine = TickEngine(state.tick_rows())
        self.brokers = ScriptedBrokerQuotes(last_prices)
        quote_service.time = FixedClock()
        mapping_cache = MappingCache(
            engine=self.engine,
            redis_connection=MappingRedisConnection(client=self.cache),
        )
        quotes = quote_service.QuoteService(mapping_cache, self.cache)
        quotes._from_broker = self.brokers.quote_from
        self.blueprint = InstrumentsBlueprint()
        self.blueprint.cache = self.cache
        self.blueprint.tokens = TokenStore(None, self.cache)
        self.blueprint._mapping_cache = mapping_cache
        self.blueprint._catalogue = InstrumentCatalogue(mapping_cache)
        self.blueprint._quotes = quotes
        self.application = flask.Flask('instruments_example')
        self.application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/instruments',
        )

    def request(self, route, query=None, body=None):
        """Opens the request context a request to one route runs in, carrying the right token.

        Args:
            route (str): The route under `/api/instruments/`.
            query (dict | None): The query string parameters of a GET.
            body (dict | None): The JSON body of a POST, or None for a GET.

        Returns:
            flask.ctx.RequestContext: The context, to enter with `with` around the handler call.
        """
        method = 'GET'
        if body is not None:
            method = 'POST'
        return self.application.test_request_context(
            f'/api/instruments/{route}',
            method=method,
            query_string=query,
            json=body,
            headers={
                'access-token': ACCESS_TOKEN,
            },
        )

    def read(self, answer):
        """Reads a handler's answer, which is a streamed response or a response and status pair.

        Args:
            answer (flask.Response | tuple): What the handler returned.

        Returns:
            tuple: The HTTP status (int) and the decoded JSON body (object).
        """
        if isinstance(answer, tuple):
            response, status = answer
        else:
            response = answer
            status = response.status_code
        return status, json.loads(response.get_data(as_text=True))

    def run(self):
        """Lists the segments, the NSE equities, a search, and the details of INFY and a small list.

        Returns:
            None: This method returns nothing.
        """
        with self.request('segments'):
            status, answer = self.read(self.blueprint.segments())
        print(f"segments: {status}, mapped on {answer['mapping_date']}")
        for segment in answer['segments']:
            print(f"  {segment['segment']}: {segment['instruments']} instruments named by {segment['identity_fields']}")

        with self.request(
            'master',
            query={
                'exchange': 'nse',
                'segment': 'equities',
            },
        ):
            status, answer = self.read(self.blueprint.master())
        symbols = []
        for instrument in answer:
            symbols.append(instrument['symbol'])
        print(f'master nse equities: {status} {symbols}')

        with self.request(
            'search',
            query={
                'exchange': 'nse',
                'segment': 'equities',
                'q': 'in',
            },
        ):
            status, answer = self.read(self.blueprint.search())
        symbols = []
        for instrument in answer['instruments']:
            symbols.append(instrument['symbol'])
        print(f'search "in": {status} {symbols}')

        with self.request(
            'details',
            query={
                'exchange': 'nse',
                'segment': 'equities',
                'symbol': 'INFY',
            },
        ):
            status, answer = self.read(self.blueprint.details())
        print(f"details INFY: {status} first seen {answer['first_seen_date']}, last seen {answer['last_seen_date']}, lot {answer['lot_size']}, tick {answer['tick_size']}")
        for handle in answer['carried_by']:
            print(f"  {handle['broker']}: token {handle['broker_token']}, order symbol {handle['order_symbol']}")

        with self.request(
            'additional_details',
            query={
                'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
            },
        ):
            status, answer = self.read(self.blueprint.additional_details())
        print(f'additional_details INFY: {status}')
        for attributes in answer['carried_by']:
            print(f"  {attributes['broker']}: isin {attributes['isin']}, display_name {attributes['display_name']}, series {attributes['series']}")

        with self.request(
            'details',
            body={
                'instruments': [
                    {
                        'instrument_id': INSTRUMENT_IDENTIFIERS['nifty_future'],
                    },
                    {
                        'exchange': 'nse',
                        'segment': 'equities',
                        'symbol': 'NOSUCHSTOCK',
                    },
                ],
            },
        ):
            status, answer = self.read(self.blueprint.details())
        print(f'details of a list: {status}')
        for entry in answer['results']:
            if entry['status'] == 200:
                data = entry['data']
                print(f"  request {entry['request_index']}: {entry['status']} {data['underlying_symbol']} future expiring {data['expiry_date']}")
            else:
                print(f"  request {entry['request_index']}: {entry['status']} {json.dumps(entry)}")


if __name__ == '__main__':
    FindingInstrumentsExample().run()
