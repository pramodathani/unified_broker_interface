"""Answers `GET /api/exchanges/details` from the Redis copy of the exchange details.

`bin/unified/user/unified_details` copies the MongoDB `exchange_details` collection into the Redis key `unified:details:exchanges` as one JSON array, and the route serves that copy without asking MongoDB at all. This program builds the blueprint, swaps its Redis client, MongoDB database and token store for small in-memory stand-ins, and calls the route's handler inside a Flask request context, which is exactly what Flask does when the request arrives.

The stand-in Redis holds the application's access token in the `last_login` hash, because every route but `POST /api/session/connect` checks the `access-token` header first. The stand-in MongoDB database holds a different document, so the output shows which store answered.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/exchanges/ExchangesBlueprint/example_1_exchange_details_from_the_cache.py
"""

import json

import flask

from unified_broker_interface.blueprints.exchanges import (
    ExchangesBlueprint,
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


class StandInCollection:
    """A stand-in for one MongoDB collection, holding its documents in a list.

    Attributes:
        documents (list): The documents.
    """

    def __init__(self, documents):
        """Builds the collection.

        Args:
            documents (list): The documents it holds.

        Returns:
            None: This method returns nothing.
        """
        self.documents = documents

    def find(self, query, projection):
        """Answers every document, as the route asks for every one.

        Args:
            query (dict): The filter, which the route always leaves empty.
            projection (dict): The fields to leave out, which the route sets to drop `_id`.

        Returns:
            list: Copies of the documents.
        """
        del query
        del projection
        found = []
        for document in self.documents:
            found.append(dict(document))
        return found


class StandInMongoDatabase:
    """A stand-in for a MongoDB database, holding its collections by name.

    Attributes:
        collections (dict): Collection names to `StandInCollection` objects.
    """

    def __init__(self, collections):
        """Builds the database.

        Args:
            collections (dict): Collection names to `StandInCollection` objects.

        Returns:
            None: This method returns nothing.
        """
        self.collections = collections

    def __getitem__(self, name):
        """Opens one collection, which is empty when it was never given.

        Args:
            name (str): The collection name.

        Returns:
            StandInCollection: The collection.
        """
        if name not in self.collections:
            self.collections[name] = StandInCollection([])
        return self.collections[name]


class ExchangeDetailsFromTheCacheExample:
    """Serves the exchange details from the Redis copy and prints the answer.

    Attributes:
        blueprint (ExchangesBlueprint): The blueprint being shown, reading the stand-ins.
        application (flask.Flask): The application whose request context the handler runs in.
    """

    def __init__(self):
        """Builds the blueprint over stand-in stores holding a token, a cached copy and a MongoDB document.

        Returns:
            None: This method returns nothing.
        """
        cache = StandInRedis()
        cache.hashes['last_login'] = {
            'unified_broker_interface': json.dumps({
                'broker_name': 'unified_broker_interface',
                'access_token': ACCESS_TOKEN,
                'last_login': '2026-09-15 08:00:00.000000',
                'expires_at': '2099-01-01 00:00:00.000000',
            }),
        }
        cache.strings['unified:details:exchanges'] = json.dumps([
            {
                'exchange': 'nse',
                'name': 'National Stock Exchange of India',
                'timezone': 'Asia/Kolkata',
            },
            {
                'exchange': 'mcx',
                'name': 'Multi Commodity Exchange of India',
                'timezone': 'Asia/Kolkata',
            },
        ])
        mongo_database = StandInMongoDatabase({
            'exchange_details': StandInCollection([
                {
                    'exchange': 'from MongoDB, not shown while the copy exists',
                },
            ]),
        })
        self.blueprint = ExchangesBlueprint()
        self.blueprint.cache = cache
        self.blueprint.mongo_db = mongo_database
        self.blueprint.tokens = TokenStore(mongo_database, cache)
        self.application = flask.Flask('exchanges_example')
        self.application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/exchanges',
        )

    def run(self):
        """Calls the handler as a request with the right token would, and prints the status and each exchange.

        Returns:
            None: This method returns nothing.
        """
        with self.application.test_request_context(
            '/api/exchanges/details',
            headers={
                'access-token': ACCESS_TOKEN,
            },
        ):
            response, status = self.blueprint.get_exchange_details()
        print(f'Status: {status}')
        for document in response.get_json():
            print(f"{document['exchange']}: {document['name']}, {document['timezone']}")


if __name__ == '__main__':
    ExchangeDetailsFromTheCacheExample().run()
