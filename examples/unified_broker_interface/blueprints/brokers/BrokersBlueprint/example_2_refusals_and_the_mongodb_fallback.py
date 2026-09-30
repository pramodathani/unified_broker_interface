"""Sends `GET /api/brokers/details` through Flask's test client: refused without the token, answered from MongoDB when there is no Redis copy, and 404 when there is nothing at all.

A client reaches the route with an HTTP request, so this program registers the blueprint on a Flask application and uses its test client, which runs the whole request in the same process. The blueprint's Redis client, MongoDB database and token store are swapped for small in-memory stand-ins, so nothing leaves the process.

Notice three things in the output. A request without the right `access-token` header is refused with 401 before any store is read. With no Redis copy of the collection, the route falls back to MongoDB, the store of record, and serves the same shape of answer. And with nothing in either store, the route answers 404 with an error message rather than an empty list.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/brokers/BrokersBlueprint/example_2_refusals_and_the_mongodb_fallback.py
"""

import json

import flask

from unified_broker_interface.blueprints.brokers import (
    BrokersBlueprint,
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


class RefusalsAndMongodbFallbackExample:
    """Sends the route three kinds of request and prints each answer.

    Attributes:
        cache (StandInRedis): The stand-in Redis client, holding the access token and no copy of the collection.
        mongo_database (StandInMongoDatabase): The stand-in MongoDB database.
        blueprint (BrokersBlueprint): The blueprint being shown, reading the stand-ins.
        client (flask.testing.FlaskClient): The test client over an application holding the blueprint.
    """

    def __init__(self):
        """Builds the blueprint over stand-in stores that hold a token and one MongoDB document, but no Redis copy.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.cache.hashes['last_login'] = {
            'unified_broker_interface': json.dumps({
                'broker_name': 'unified_broker_interface',
                'access_token': ACCESS_TOKEN,
                'last_login': '2026-09-15 08:00:00.000000',
                'expires_at': '2099-01-01 00:00:00.000000',
            }),
        }
        self.mongo_database = StandInMongoDatabase({
            'broker_details': StandInCollection([
                {
                    'broker_name': 'fyers',
                    'sebi_registration': 'INZ000000003',
                },
            ]),
        })
        self.blueprint = BrokersBlueprint()
        self.blueprint.cache = self.cache
        self.blueprint.mongo_db = self.mongo_database
        self.blueprint.tokens = TokenStore(self.mongo_database, self.cache)
        application = flask.Flask('brokers_example')
        application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/brokers',
        )
        self.client = application.test_client()

    def show(self, title, headers):
        """Sends one request and prints its status and body.

        Args:
            title (str): What the request shows.
            headers (dict): The request headers.

        Returns:
            None: This method returns nothing.
        """
        response = self.client.get('/api/brokers/details', headers=headers)
        print(f'{title}: {response.status_code} {json.dumps(response.get_json())}')

    def run(self):
        """Sends a request with a wrong token, one served from MongoDB, and one with both stores empty.

        Returns:
            None: This method returns nothing.
        """
        good_headers = {
            'access-token': ACCESS_TOKEN,
        }
        wrong_headers = {
            'access-token': 'not-the-token',
        }
        self.show('Wrong token', wrong_headers)
        self.show('No Redis copy', good_headers)
        self.mongo_database.collections['broker_details'].documents = []
        self.show('Nothing stored', good_headers)


if __name__ == '__main__':
    RefusalsAndMongodbFallbackExample().run()
