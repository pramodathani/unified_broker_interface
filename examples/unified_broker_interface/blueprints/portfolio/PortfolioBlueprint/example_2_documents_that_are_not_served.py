"""Shows when the portfolio routes refuse to serve a document: when it is missing, out of date, or holds no broker's data.

A route never serves a document it cannot trust. A document that is missing or unreadable means its script is not running, and is answered with 503. A document older than the route allows means its script has stopped, and is also answered with 503, with its `as_of` and `brokers` so a client never mistakes an old book for today's. A document in which no broker was read, every broker `missing` or `unreadable`, is answered with 502, still listing each broker's status.

This program sends `GET /api/portfolio/funds`, `/holdings` and `/positions` through Flask's test client, with the blueprint's Redis client swapped for an in-memory stand-in. It also shows the 401 a request without a token gets before any document is read. Every `as_of` it prints is a fixed date in the past, or is not printed, so the output is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/portfolio/PortfolioBlueprint/example_2_documents_that_are_not_served.py
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


class DocumentsThatAreNotServedExample:
    """Stores a missing, an old and an unread document and prints each route's refusal.

    Attributes:
        cache (StandInRedis): The stand-in Redis client.
        blueprint (PortfolioBlueprint): The blueprint being shown.
        application (flask.Flask): The application holding the blueprint.
    """

    def __init__(self):
        """Stores an old holdings document and a positions document in which no broker was read, and no funds document at all.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.blueprint = None
        self.application = None
        self.build_blueprint()
        self.cache.strings['unified:portfolio:holdings'] = json.dumps({
            'holdings': [],
            'brokers': [
                {
                    'broker': 'zerodha',
                    'status': 'ok',
                },
            ],
            'as_of': '2026-09-14T15:30:00',
        })
        self.cache.strings['unified:portfolio:positions'] = json.dumps({
            'net': [],
            'brokers': [
                {
                    'broker': 'zerodha',
                    'status': 'missing',
                },
                {
                    'broker': 'dhan',
                    'status': 'unreadable',
                },
            ],
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

    def run(self):
        """Sends each route once with the token and once without, and prints the answers.

        Returns:
            None: This method returns nothing.
        """
        client = self.application.test_client()
        headers = {
            'access-token': ACCESS_TOKEN,
        }
        for name in [
            'funds',
            'holdings',
            'positions',
        ]:
            response = client.get(f'/api/portfolio/{name}', headers=headers)
            print(f'/{name}: {response.status_code} {json.dumps(response.get_json(), sort_keys=True)}')
        response = client.get('/api/portfolio/funds')
        print(f'/funds without a token: {response.status_code} {json.dumps(response.get_json())}')


if __name__ == '__main__':
    DocumentsThatAreNotServedExample().run()
