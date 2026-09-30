"""Serves the account's funds, holdings and positions, each combined across every broker by its `bin/unified/portfolio/` script.

Each route answers with a document a script keeps in Redis, rather than asking the brokers while the client waits: `unified:portfolio:funds` and `unified:portfolio:positions` are rewritten every half second and served while they are at most 30 seconds old, and `unified:portfolio:holdings` is rewritten every minute and served while it is at most five minutes old. Each document carries `as_of`, when it was written, and `brokers`, how each broker's data was read.

This program writes the three documents into an in-memory stand-in for Redis with `as_of` set to the moment the program runs, as a running script would, and calls each handler inside a Flask request context. It prints everything except `as_of`, which changes on every run.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/portfolio/PortfolioBlueprint/example_1_funds_holdings_and_positions.py
"""

import datetime
import json

import flask

from unified_broker_interface.blueprints.portfolio import (
    PortfolioBlueprint,
)
from unified_broker_interface.utilities.tokens import (
    TokenStore,
)

ACCESS_TOKEN = 'example-access-token'


class StandInRedis:
    """A stand-in for the Redis client that holds strings and hashes in memory.

    Attributes:
        strings (dict): String keys to their values.
        hashes (dict): Hash keys to dictionaries of fields and values.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}
        self.hashes = {}

    def get(self, key):
        """Reads a string key.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when the key is missing.
        """
        return self.strings.get(key)

    def hget(self, key, field):
        """Reads one field of a hash.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None when it is missing.
        """
        return self.hashes.get(key, {}).get(field)

    def hsetnx(self, key, field, value):
        """Writes one field of a hash only when it is empty.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            bool: True when the field was written.
        """
        fields = self.hashes.setdefault(key, {})
        if field in fields:
            return False
        fields[field] = value
        return True


class FundsHoldingsAndPositionsExample:
    """Writes the three portfolio documents and prints what each route answers.

    Attributes:
        cache (StandInRedis): The stand-in Redis client holding the documents.
        blueprint (PortfolioBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
    """

    def __init__(self):
        """Writes a fresh funds, holdings and positions document into the stand-in and builds the blueprint.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.blueprint = None
        self.application = None
        self.build_blueprint()
        brokers = [
            {
                'broker': 'zerodha',
                'status': 'ok',
            },
            {
                'broker': 'dhan',
                'status': 'stale',
            },
        ]
        self.cache.strings['unified:portfolio:funds'] = json.dumps({
            'summary': {
                'total_balance': 250000.0,
                'available_balance': 200000.0,
                'margin_utilized': 50000.0,
            },
            'brokers': brokers,
            'as_of': self.written_now(),
        })
        self.cache.strings['unified:portfolio:holdings'] = json.dumps({
            'holdings': [
                {
                    'symbol': 'INFY',
                    'quantity': 10,
                    'last_price': 1521.4,
                },
            ],
            'brokers': brokers,
            'as_of': self.written_now(),
        })
        self.cache.strings['unified:portfolio:positions'] = json.dumps({
            'net': [
                {
                    'symbol': 'NIFTY26OCTFUT',
                    'quantity': 75,
                    'pnl': 1250.0,
                },
            ],
            'brokers': brokers,
            'as_of': self.written_now(),
        })

    def build_blueprint(self):
        """Builds the blueprint over the stand-in Redis client and registers it on a Flask application.

        The routes read nothing from MongoDB, so the blueprint and its token store are given None for it.

        Returns:
            None: This method returns nothing.
        """
        self.cache.hashes['last_login'] = {
            'unified_broker_interface': json.dumps({
                'broker_name': 'unified_broker_interface',
                'access_token': ACCESS_TOKEN,
                'last_login': '2026-09-15 08:00:00.000000',
                'expires_at': '2099-01-01 00:00:00.000000',
            }),
        }
        self.blueprint = PortfolioBlueprint()
        self.blueprint.cache = self.cache
        self.blueprint.mongo_db = None
        self.blueprint.tokens = TokenStore(None, self.cache)
        self.application = flask.Flask('portfolio_example')
        self.application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/portfolio',
        )

    def written_now(self):
        """The `as_of` a document written by its script a moment ago carries.

        Returns:
            str: The current local time in the unified documents' format.
        """
        return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    def request(self, name):
        """Opens the request context a request to one route runs in, carrying the right token.

        Args:
            name (str): The route's name under `/api/portfolio/`.

        Returns:
            flask.ctx.RequestContext: The context, to enter with `with` around the handler call.
        """
        return self.application.test_request_context(
            f'/api/portfolio/{name}',
            headers={
                'access-token': ACCESS_TOKEN,
            },
        )

    def show(self, name, answer):
        """Prints a handler's status and its document without `as_of`.

        Args:
            name (str): The route's name.
            answer (tuple): The Flask JSON response (flask.Response) and HTTP status (int) the handler returned.

        Returns:
            None: This method returns nothing.
        """
        response, status = answer
        document = response.get_json()
        document.pop('as_of')
        print(f'/{name}: {status} {json.dumps(document, sort_keys=True)}')

    def run(self):
        """Prints the answer of each of the three routes.

        Returns:
            None: This method returns nothing.
        """
        with self.request('funds'):
            self.show('funds', self.blueprint.funds())
        with self.request('holdings'):
            self.show('holdings', self.blueprint.holdings())
        with self.request('positions'):
            self.show('positions', self.blueprint.positions())


if __name__ == '__main__':
    FundsHoldingsAndPositionsExample().run()
