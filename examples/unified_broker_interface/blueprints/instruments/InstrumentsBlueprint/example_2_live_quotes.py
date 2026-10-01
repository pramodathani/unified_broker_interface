"""Reads live prices with `/api/instruments/ltp`, `/ohlc` and `/quote`, from the quote cache or, when that is not recent enough, from a broker.

The quote routes answer from `unified:quotes:live`, the hash the unified quote script keeps, when the instrument's quote there is recent enough. Otherwise they ask a broker that carries the instrument over its REST API, in the order the quote sources rank them, and answer with the first quote that comes back. `ltp` narrows the unified quote document to the last price, `ohlc` answers only the day's open, high, low, close and volume, where the close is the last traded price, and `quote` returns the whole document, market depth included. Each also takes a list of instruments by POST.

This program pins the quote service's clock to 10:00 IST on 15 September 2026, when INFY's cached quote is a minute old and RELIANCE's is an hour old, and replaces asking a broker with a small stand-in that answers with a fixed price. The catalogue and the cached quotes come from the offline instrument route suite, `test_runs/instrument_routes.py`. Notice in the output which answers came from the cache and which brokers were asked.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/instruments/InstrumentsBlueprint/example_2_live_quotes.py
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


LAST_PRICES = {
    'zerodha': 2876.5,
}


class LiveQuotesExample:
    """Asks for the last price, the OHLC and whole quotes, and prints where each answer came from.

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
        """Asks for INFY's last price, RELIANCE's OHLC, and the quotes of a list of four instruments.

        Returns:
            None: This method returns nothing.
        """
        with self.request(
            'ltp',
            query={
                'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
            },
        ):
            status, answer = self.read(self.blueprint.ltp())
        print(f"ltp INFY: {status} {answer['last_price']} from {answer['source']}")
        print(f'  brokers asked: {self.brokers.asked}')

        with self.request(
            'ohlc',
            query={
                'exchange': 'nse',
                'segment': 'equities',
                'symbol': 'RELIANCE',
            },
        ):
            status, answer = self.read(self.blueprint.ohlc())
        print(f"ohlc RELIANCE: {status} {json.dumps(answer, sort_keys=True)}")
        print(f'  brokers asked: {self.brokers.asked}')

        self.brokers.asked = []
        with self.request(
            'quote',
            body={
                'instruments': [
                    {
                        'instrument_id': INSTRUMENT_IDENTIFIERS['infy'],
                    },
                    {
                        'instrument_id': INSTRUMENT_IDENTIFIERS['nifty_option'],
                    },
                    {
                        'instrument_id': INSTRUMENT_IDENTIFIERS['unquoted'],
                    },
                    {
                        'instrument_id': INSTRUMENT_IDENTIFIERS['unknown'],
                    },
                ],
            },
        ):
            status, answer = self.read(self.blueprint.quote())
        print(f'quote of a list: {status}')
        for entry in answer['results']:
            if entry['status'] == 200:
                data = entry['data']
                print(f"  request {entry['request_index']}: {entry['status']} {data['instrument_id']} last {data['last_price']} from {data['source']}, depth {json.dumps(data['depth'], sort_keys=True)}")
            else:
                print(f"  request {entry['request_index']}: {entry['status']} {entry['error']}")
        print(f'  brokers asked: {self.brokers.asked}')


if __name__ == '__main__':
    LiveQuotesExample().run()
