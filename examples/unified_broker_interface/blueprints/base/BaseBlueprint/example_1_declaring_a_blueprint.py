"""Declares a new blueprint as a subclass of `BaseBlueprint` and shows how its routes are registered and where its documents come from.

A subclass sets `name` and `routes`, a list of `(url_rule, method_name, http_methods)`, and constructing it builds a Flask blueprint with each route bound to the named method of the instance. The instance also opens the MongoDB database and Redis client every request shares, and a token store built from them for the `authenticated` decorator.

The subclass here, `HolidaysBlueprint`, serves a MongoDB collection of trading holidays through `list_collection`, the way the brokers and exchanges blueprints serve theirs. After building it, the program swaps its stores for small in-memory stand-ins, lists the rules Flask registered, and calls `collection_documents` twice: once while the Redis copy exists, and once after it is removed, when the documents come from MongoDB instead.

Run it from the project root:

    python examples/unified_broker_interface/blueprints/base/BaseBlueprint/example_1_declaring_a_blueprint.py
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


class HolidaysBlueprint(BaseBlueprint):
    """The `/api/holidays` routes: the trading holidays, from MongoDB or its Redis copy."""

    name = 'holidays'
    routes = [
        (
            '/details',
            'get_holidays',
            [
                'GET',
            ],
        ),
    ]

    @authenticated
    def get_holidays(self):
        """Answers every trading holiday, or 404 when none are stored.

        Returns:
            tuple: The Flask JSON response (flask.Response) and its HTTP status (int).
        """
        return self.list_collection('holidays', 'unified:details:holidays', 'Holidays not found')


class DeclaringABlueprintExample:
    """Builds the subclass, registers it and prints its routes and documents.

    Attributes:
        cache (StandInRedis): The stand-in Redis client.
        blueprint (HolidaysBlueprint): The blueprint being shown.
        application (flask.Flask): The application holding the blueprint.
    """

    def __init__(self):
        """Builds the blueprint and swaps its stores for stand-ins holding a Redis copy and a different MongoDB document.

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
        self.cache.strings['unified:details:holidays'] = json.dumps([
            {
                'date': '2026-10-02',
                'description': 'Gandhi Jayanti',
            },
            {
                'date': '2026-10-20',
                'description': 'Diwali',
            },
        ])
        mongo_database = StandInMongoDatabase({
            'holidays': StandInCollection([
                {
                    'date': '2026-12-25',
                    'description': 'Christmas',
                },
            ]),
        })
        self.blueprint = HolidaysBlueprint()
        self.blueprint.cache = self.cache
        self.blueprint.mongo_db = mongo_database
        self.blueprint.tokens = TokenStore(mongo_database, self.cache)
        self.application = flask.Flask('holidays_example')
        self.application.register_blueprint(
            self.blueprint.blueprint,
            url_prefix='/api/holidays',
        )

    def run(self):
        """Prints the registered rules, the documents with and without the Redis copy, and the route's answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'Blueprint name: {self.blueprint.blueprint.name}')
        for rule in self.application.url_map.iter_rules():
            if rule.endpoint.startswith('holidays.'):
                print(f'Rule: {rule.rule} -> {rule.endpoint} {sorted(rule.methods)}')
        documents = self.blueprint.collection_documents('holidays', 'unified:details:holidays')
        print(f'With the Redis copy: {documents}')
        del self.cache.strings['unified:details:holidays']
        documents = self.blueprint.collection_documents('holidays', 'unified:details:holidays')
        print(f'Without it, from MongoDB: {documents}')
        with self.application.test_request_context(
            '/api/holidays/details',
            headers={
                'access-token': ACCESS_TOKEN,
            },
        ):
            response, status = self.blueprint.list_collection('holidays', 'unified:details:holidays', 'Holidays not found')
        print(f'list_collection: {status} {json.dumps(response.get_json())}')


if __name__ == '__main__':
    DeclaringABlueprintExample().run()
