"""Answers `GET /api/users/details`: the account holder's profile documents together with every broker's own profile of the account.

The route reads two things. The profile documents come from the MongoDB `user_details` collection, or from its Redis copy `unified:details:users` when `bin/unified/user/unified_details` keeps one. Each broker's profile comes from the single Redis key `unified:user:details`, an object with one key per broker, which `bin/unified/user/details` keeps; a broker whose profile could not be read has null there.

This program swaps the blueprint's stores for small in-memory stand-ins holding a token, a cached profile document and two brokers' profiles, one of them null, and calls the handler inside a Flask request context. It also calls `broker_profiles` on its own, which is the part of the route that reads the brokers' profiles.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/users/UsersBlueprint/example_1_profile_with_broker_profiles.py
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


class ProfileWithBrokerProfilesExample:
    """Serves the profile documents and the brokers' profiles and prints them.

    Attributes:
        cache (StandInRedis): The stand-in Redis client.
        mongo_database (StandInMongoDatabase): The stand-in MongoDB database.
        blueprint (UsersBlueprint): The blueprint being shown.
        application (flask.Flask): The application whose request context the handler runs in.
    """

    def __init__(self):
        """Fills the stand-ins with a cached profile document and the brokers' profiles, then builds the blueprint.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        self.mongo_database = StandInMongoDatabase({})
        self.cache.strings['unified:details:users'] = json.dumps([
            {
                'user_name': 'Example Account Holder',
                'email': 'holder@example.com',
                'pan': 'ABCDE1234F',
            },
        ])
        self.cache.strings['unified:user:details'] = json.dumps({
            'zerodha': {
                'user_id': 'AB1234',
                'user_name': 'Example Account Holder',
                'exchanges': [
                    'NSE',
                    'BSE',
                ],
            },
            'dhan': None,
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

    def run(self):
        """Prints the brokers' profiles on their own, then the route's whole answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'broker_profiles(): {json.dumps(self.blueprint.broker_profiles(), sort_keys=True)}')
        with self.application.test_request_context(
            '/api/users/details',
            headers={
                'access-token': ACCESS_TOKEN,
            },
        ):
            response, status = self.blueprint.get_user_profile()
        print(f'Status: {status}')
        print(json.dumps(response.get_json(), indent=2, sort_keys=True))


if __name__ == '__main__':
    ProfileWithBrokerProfilesExample().run()
