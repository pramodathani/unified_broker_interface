"""Shows what the users route does when the brokers' profiles are missing or unreadable, and when there is nothing to serve at all.

`broker_profiles` never raises. It answers None when the Redis key `unified:user:details` is missing, holds text that is not JSON, or holds JSON that is not an object, so a Redis without the key still serves the profile documents. Only when there are no profile documents and no broker has a profile does `GET /api/users/details` answer 404.

This program sends the route through Flask's test client, with the blueprint's stores swapped for small in-memory stand-ins, and changes what the stand-in Redis holds between requests. The profile documents come from the MongoDB stand-in in the first request, because there is no Redis copy of them.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/users/UsersBlueprint/example_2_missing_broker_profiles.py
"""

import json

import flask

from unified_broker_interface.blueprints.users import (
    UsersBlueprint,
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


class MissingBrokerProfilesExample:
    """Changes the stored profiles between requests and prints what the route answers each time.

    Attributes:
        cache (StandInRedis): The stand-in Redis client.
        mongo_database (StandInMongoDatabase): The stand-in MongoDB database.
        blueprint (UsersBlueprint): The blueprint being shown.
        application (flask.Flask): The application holding the blueprint.
    """

    def __init__(self):
        """Builds the blueprint over stand-ins holding one MongoDB profile document and no broker profiles.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.mongo_database = StandInMongoDatabase({
            'user_details': StandInCollection([
                {
                    'user_name': 'Example Account Holder',
                },
            ]),
        })
        self.blueprint = None
        self.application = None
        self.build_blueprint()

    def build_blueprint(self):
        """Builds the blueprint over the stand-ins and registers it on a Flask application.

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
        self.blueprint = UsersBlueprint()
        self.blueprint.cache = self.cache
        self.blueprint.mongo_db = self.mongo_database
        self.blueprint.tokens = TokenStore(self.mongo_database, self.cache)
        self.application = flask.Flask('users_example')
        self.application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/users',
        )

    def show(self, title):
        """Prints what `broker_profiles` reads now and what the route answers.

        Args:
            title (str): What the stores hold at this point.

        Returns:
            None: This method returns nothing.
        """
        client = self.application.test_client()
        response = client.get(
            '/api/users/details',
            headers={
                'access-token': ACCESS_TOKEN,
            },
        )
        print(title)
        print(f'  broker_profiles(): {self.blueprint.broker_profiles()}')
        print(f'  {response.status_code} {json.dumps(response.get_json(), sort_keys=True)}')

    def run(self):
        """Sends the route four times, with the brokers' profiles missing, unreadable, a list, and with nothing stored at all.

        Returns:
            None: This method returns nothing.
        """
        self.show('Key missing')
        self.cache.strings['unified:user:details'] = 'not json'
        self.show('Key unreadable')
        self.cache.strings['unified:user:details'] = json.dumps([
            'zerodha',
        ])
        self.show('Key holds a list')
        self.mongo_database.collections['user_details'].documents = []
        self.cache.strings['unified:user:details'] = json.dumps({
            'zerodha': None,
        })
        self.show('No documents and no broker profile')


if __name__ == '__main__':
    MissingBrokerProfilesExample().run()
