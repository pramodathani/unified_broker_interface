"""Asks `/api/instruments/breakeven` for the floor, tripwire and switch-on of a NIFTY option bought at 177.00.

The route resolves the instrument from the catalogue, reads its tick size from its details and its spread from its live quote, and hands them to the blueprint's `BreakevenLevels` service with the position's entry price, quantity, side, product and broker. This program builds the blueprint over the in-memory Redis stand-in of the offline instrument route suite, and gives it a levels service over the in-memory tables of the breakeven levels suite, so it needs no Redis or PostgreSQL. The option has no quote in the stand-in catalogue, so the answer shows what the route does without one.

Notice that without a quote the tripwire and switch-on come from the measured slips and flicker alone, and that a request missing the quantity is answered 400.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/instruments/InstrumentsBlueprint/example_4_breakeven_levels.py
"""

import decimal
import json

import flask

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingCache,
    MappingRedisConnection,
)
from test_runs.breakeven_levels import SEGMENT, BreakevenLevelsSuite
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
from unified_broker_interface.utilities.tokens import (
    TokenStore,
)

ACCESS_TOKEN = 'api-token'


class NoBrokerQuotes:
    """Stands in for asking a broker for a quote, and never has one."""

    def quote_from(self, broker, handle, identity, cached, now):
        """Refuses every quote.

        Args:
            broker (str): The broker asked.
            handle (dict): The broker's handle.
            identity (dict): The instrument's identity.
            cached (dict | None): The cached quote.
            now (float): The instant, as epoch seconds.

        Returns:
            dict: Never returns.

        Raises:
            QuoteUnavailable: Always.
        """
        del handle
        del identity
        del cached
        del now
        raise QuoteUnavailable(f'{broker} has no quote in this example')


class BreakevenLevelsExample:
    """Asks the route for one position's levels.

    Attributes:
        blueprint (InstrumentsBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handler runs in.
    """

    def __init__(self):
        """Builds the blueprint over the stand-ins and gives it a levels service.

        Returns:
            None: This method returns nothing.
        """
        state = InstrumentRoutesState()
        filled = state.build()
        cache = InstrumentRoutesRedis()
        cache.strings = filled.strings
        cache.hashes = filled.hashes
        cache.sorted_sets = filled.sorted_sets
        mapping_cache = MappingCache(
            engine=TickEngine(state.tick_rows()),
            redis_connection=MappingRedisConnection(client=cache),
        )
        quotes = quote_service.QuoteService(mapping_cache, cache)
        quotes._from_broker = NoBrokerQuotes().quote_from
        self.blueprint = InstrumentsBlueprint()
        self.blueprint.cache = cache
        self.blueprint.tokens = TokenStore(None, cache)
        self.blueprint._mapping_cache = mapping_cache
        self.blueprint._catalogue = InstrumentCatalogue(mapping_cache)
        self.blueprint._quotes = quotes
        suite = BreakevenLevelsSuite()
        slips = []
        for index in range(40):
            slips.append((SEGMENT, 'SELL', decimal.Decimal('58')))
        service, database = suite.service(suite.sawtooth_ticks(), slips)
        del database
        self.blueprint._breakeven_levels = service
        self.application = flask.Flask('breakeven_example')
        self.application.register_blueprint(self.blueprint.blueprint, url_prefix='/api/instruments')

    def ask(self, query):
        """Calls the route with a query string and prints its status and answer.

        Args:
            query (dict): The query string parameters.

        Returns:
            None: This method returns nothing.
        """
        with self.application.test_request_context('/api/instruments/breakeven', query_string=query, headers={'access-token': ACCESS_TOKEN}):
            response, status = self.blueprint.breakeven()
        answer = json.loads(response.get_data(as_text=True))
        if status != 200:
            print(f'{status}: {answer}')
            return
        print(f'{status}: {answer["segment"]} at {answer["broker"]}, spread {answer["spread"]}')
        for name in ('floor', 'tripwire', 'switch_on'):
            level = answer[name]
            print(f'  {name}: {level["price"]} (+{level["distance_from_entry"]})')

    def run(self):
        """Asks for a bought position's levels, then makes a request without a quantity.

        Returns:
            None: This method returns nothing.
        """
        option = INSTRUMENT_IDENTIFIERS['nifty_option']
        self.ask({'instrument_id': option, 'entry_price': '177', 'quantity': '65', 'side': 'BUY'})
        self.ask({'instrument_id': option, 'entry_price': '177'})


if __name__ == '__main__':
    BreakevenLevelsExample().run()
