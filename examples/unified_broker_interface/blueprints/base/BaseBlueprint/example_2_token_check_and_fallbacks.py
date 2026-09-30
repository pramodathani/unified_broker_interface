"""Shows the two safety nets `BaseBlueprint` gives every route: the `authenticated` token check, and serving from MongoDB when the Redis copy cannot be used.

The `authenticated` decorator refuses a request with 401 unless its `access-token` header carries the token in force, before the handler runs. `collection_documents` treats a Redis copy that is missing, is not JSON, or is JSON but not an array the same way, by reading MongoDB, the store of record, and `list_collection` turns an empty collection into a 404 with the message the route gives.

This program declares a small subclass with one route, `GET /api/notes/details`, swaps its stores for in-memory stand-ins, and sends requests through Flask's test client while changing what the stand-in Redis holds.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/base/BaseBlueprint/example_2_token_check_and_fallbacks.py
"""

import json

import flask

from unified_broker_interface.blueprints.base import (
    BaseBlueprint,
    authenticated,
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


class NotesBlueprint(BaseBlueprint):
    """The `/api/notes` routes: operator notes, from MongoDB or its Redis copy."""

    name = 'notes'
    routes = [
        (
            '/details',
            'get_notes',
            [
                'GET',
            ],
        ),
    ]

    @authenticated
    def get_notes(self):
        """Answers every note, or 404 when none are stored.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        return self.list_collection('notes', 'unified:details:notes', 'Notes not found')


class TokenCheckAndFallbacksExample:
    """Sends the route requests with bad tokens and bad Redis copies and prints each answer.

    Attributes:
        cache (StandInRedis): The stand-in Redis client.
        mongo_database (StandInMongoDatabase): The stand-in MongoDB database.
        blueprint (NotesBlueprint): The blueprint being shown.
        client (flask.testing.FlaskClient): The test client over an application holding the blueprint.
    """

    def __init__(self):
        """Builds the blueprint over stand-ins holding the token and one MongoDB note.

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
            'notes': StandInCollection([
                {
                    'note': 'Kotak login needs a new TOTP secret',
                },
            ]),
        })
        self.blueprint = NotesBlueprint()
        self.blueprint.cache = self.cache
        self.blueprint.mongo_db = self.mongo_database
        self.blueprint.tokens = TokenStore(self.mongo_database, self.cache)
        application = flask.Flask('notes_example')
        application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/notes',
        )
        self.client = application.test_client()

    def show(self, title, access_token):
        """Sends one request and prints its status and body.

        Args:
            title (str): What the request shows.
            access_token (str | None): The `access-token` header, or None to send none.

        Returns:
            None: This method returns nothing.
        """
        headers = {}
        if access_token is not None:
            headers['access-token'] = access_token
        response = self.client.get('/api/notes/details', headers=headers)
        print(f'{title}: {response.status_code} {json.dumps(response.get_json())}')

    def run(self):
        """Sends requests without a token, with a wrong one, with unusable Redis copies, and with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.show('No token', None)
        self.show('Wrong token', 'guessed-token')
        self.cache.strings['unified:details:notes'] = 'not json'
        self.show('Redis copy is not JSON', ACCESS_TOKEN)
        self.cache.strings['unified:details:notes'] = json.dumps({
            'note': 'an object, not an array',
        })
        self.show('Redis copy is not an array', ACCESS_TOKEN)
        del self.cache.strings['unified:details:notes']
        self.mongo_database.collections['notes'].documents = []
        documents = self.blueprint.collection_documents('notes', 'unified:details:notes')
        print(f'collection_documents with nothing stored: {documents}')
        self.show('Nothing stored', ACCESS_TOKEN)


if __name__ == '__main__':
    TokenCheckAndFallbacksExample().run()
