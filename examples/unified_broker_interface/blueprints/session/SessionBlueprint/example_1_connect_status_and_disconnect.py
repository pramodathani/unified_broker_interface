"""Connects, checks the session and disconnects: the life of one access token at `/api/session`.

`POST /api/session/connect` exchanges the `api-key` and `api-secret` headers for the access token every other route needs. When the stored token was issued since the most recent 07:00 and is still accepted, connect hands that same token back rather than minting a new one, so several clients share one session. `GET /api/session/status` reports the session as connected, and `DELETE /api/session/disconnect` revokes the token, after which the token is refused everywhere.

This program swaps the blueprint's MongoDB database and Redis client for small in-memory stand-ins, stores the application's key and secret and a token issued this morning, and calls each handler inside a Flask request context. The stored token is issued at the moment the program runs, so connect always finds it current, and the output shows the same token coming back.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/session/SessionBlueprint/example_1_connect_status_and_disconnect.py
"""

import datetime
import json

import flask

from unified_broker_interface.blueprints.session import (
    SessionBlueprint,
)
from unified_broker_interface.utilities.tokens import (
    TokenStore,
)

API_KEY = 'example-api-key'
API_SECRET = 'example-api-secret'
STORED_TOKEN = 'token-issued-this-morning'


class StandInRedis:
    """A stand-in for the Redis client that holds hashes in memory.

    Attributes:
        hashes (dict): Hash keys to dictionaries of fields and values.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}

    def hget(self, key, field):
        """Reads one field of a hash.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None when it is missing.
        """
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field, value):
        """Writes one field of a hash.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            int: 1, as if the field were new.
        """
        self.hashes.setdefault(key, {})[field] = value
        return 1

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

    def hdel(self, key, field):
        """Deletes one field of a hash.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            int: 1 when the field existed, otherwise 0.
        """
        fields = self.hashes.get(key, {})
        if field in fields:
            del fields[field]
            return 1
        return 0


class StandInCollection:
    """A stand-in for one MongoDB collection whose documents are keyed by `broker_name`.

    Attributes:
        documents (dict): Each document's `broker_name` to the document.
    """

    def __init__(self):
        """Builds an empty collection.

        Returns:
            None: This method returns nothing.
        """
        self.documents = {}

    def find_one(self, query, projection):
        """Finds the document with the `broker_name` the query names.

        Args:
            query (dict): The filter, which names `broker_name`.
            projection (dict): The fields to leave out, which the callers set to drop `_id`.

        Returns:
            dict | None: A copy of the document, or None when there is none.
        """
        del projection
        document = self.documents.get(query['broker_name'])
        if document is None:
            return None
        return dict(document)

    def replace_one(self, query, document, upsert):
        """Replaces, or with `upsert` adds, the document with the `broker_name` the query names.

        Args:
            query (dict): The filter, which names `broker_name`.
            document (dict): The new document.
            upsert (bool): Whether to add the document when there is none.

        Returns:
            None: This method returns nothing.
        """
        if upsert or query['broker_name'] in self.documents:
            self.documents[query['broker_name']] = dict(document)


class StandInMongoDatabase:
    """A stand-in for a MongoDB database, holding its collections by name.

    Attributes:
        collections (dict): Collection names to `StandInCollection` objects.
    """

    def __init__(self):
        """Builds a database with no collections yet.

        Returns:
            None: This method returns nothing.
        """
        self.collections = {}

    def __getitem__(self, name):
        """Opens one collection, creating it empty the first time.

        Args:
            name (str): The collection name.

        Returns:
            StandInCollection: The collection.
        """
        if name not in self.collections:
            self.collections[name] = StandInCollection()
        return self.collections[name]


class ConnectStatusAndDisconnectExample:
    """Takes one token through connect, status and disconnect and prints each answer.

    Attributes:
        cache (StandInRedis): The stand-in Redis client.
        mongo_database (StandInMongoDatabase): The stand-in MongoDB database.
        blueprint (SessionBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handlers run in.
    """

    def __init__(self):
        """Builds the blueprint over stand-ins holding the key, the secret and a token issued this morning.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.mongo_database = StandInMongoDatabase()
        self.blueprint = None
        self.application = None
        self.build_blueprint()
        self.store_login(STORED_TOKEN, '2099-01-01 00:00:00.000000')

    def build_blueprint(self):
        """Stores the application's api key and secret, builds the blueprint over the stand-ins and registers it on a Flask application.

        Returns:
            None: This method returns nothing.
        """
        self.mongo_database['settings'].documents['unified_broker_interface'] = {
            'broker_name': 'unified_broker_interface',
            'api_key': API_KEY,
            'api_secret': API_SECRET,
        }
        self.blueprint = SessionBlueprint()
        self.blueprint.cache = self.cache
        self.blueprint.mongo_db = self.mongo_database
        self.blueprint.tokens = TokenStore(self.mongo_database, self.cache)
        self.application = flask.Flask('session_example')
        self.application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/session',
        )

    def store_login(self, access_token, expires_at):
        """Stores a login document for the application in both stand-in stores, issued at the moment the program runs.

        Args:
            access_token (str): The token in force.
            expires_at (str): When it expires, in the login documents' format.

        Returns:
            None: This method returns nothing.
        """
        document = {
            'broker_name': 'unified_broker_interface',
            'access_token': access_token,
            'last_login': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
            'expires_at': expires_at,
        }
        self.mongo_database['last_login'].documents['unified_broker_interface'] = document
        self.cache.hset('last_login', 'unified_broker_interface', json.dumps(document))

    def run(self):
        """Connects with the key and secret, then checks the status, disconnects and checks it again.

        Returns:
            None: This method returns nothing.
        """
        with self.application.test_request_context(
            '/api/session/connect',
            method='POST',
            environ_base={
                'REMOTE_ADDR': '127.0.0.1',
            },
            headers={
                'api-key': API_KEY,
                'api-secret': API_SECRET,
            },
        ):
            response, status = self.blueprint.connect()
        answer = response.get_json()
        print(f'connect: {status} {json.dumps(answer, sort_keys=True)}')
        token_headers = {
            'access-token': answer['access-token'],
        }
        with self.application.test_request_context('/api/session/status', headers=token_headers):
            response, status = self.blueprint.status()
        print(f'status: {status} {json.dumps(response.get_json(), sort_keys=True)}')
        with self.application.test_request_context(
            '/api/session/disconnect',
            method='DELETE',
            headers=token_headers,
        ):
            response, status = self.blueprint.disconnect()
        print(f'disconnect: {status} {json.dumps(response.get_json())}')
        with self.application.test_request_context('/api/session/status', headers=token_headers):
            response, status = self.blueprint.status()
        print(f'status after disconnect: {status} {json.dumps(response.get_json())}')
        stored = self.mongo_database['last_login'].documents['unified_broker_interface']
        print(f"Stored access_token after disconnect: {stored['access_token']}")


if __name__ == '__main__':
    ConnectStatusAndDisconnectExample().run()
