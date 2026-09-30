"""Walks the REST API's access token through one day: connect, check requests, connect again, and disconnect.

The REST API has one access token at a time. `TokenStore` keeps it as a login document in the MongoDB `last_login` collection, mirrored into the Redis `last_login` hash, exactly as each broker's login is kept. `connect` hands back the token in force when it was issued since the most recent 07:00, and mints a new one otherwise. `check` decides whether a request's `access-token` header is acceptable, and `revoke` ends the session at once.

This program replaces MongoDB and Redis with two small stand-ins that keep the document in dictionaries. It starts with a token issued on 5 January 2026, long before the most recent 07:00, so the first connect mints a new token. A minted token is random and stamped with the current time, so the program prints only facts about it that are the same on every run, never the token or the time.

Notice that the old token is replaced, that the second connect returns the same token without minting, that a request with the token is accepted while one with the January token is refused, and that after `revoke` the token is refused too.

Run it from the project root:

    python examples/unified_broker_interface/utilities/tokens/TokenStore/example_1_connect_check_and_disconnect.py
"""

import datetime
import json
import uuid

from unified_broker_interface.utilities.tokens import (
    TokenStore,
)

OLD_TOKEN = '5b0c9d0e-8f7a-4c35-9a53-2f4f0f4f7a61'


class StandInCollection:
    """A stand-in MongoDB collection holding login documents by `broker_name`.

    Attributes:
        documents (dict): The documents by broker name.
    """

    def __init__(self):
        """Builds an empty collection.

        Returns:
            None: This method returns nothing.
        """
        self.documents = {}

    def find_one(self, query, projection):
        """Finds the document for one broker name.

        Args:
            query (dict): The filter, naming `broker_name`.
            projection (dict): The fields to leave out, which the stand-in ignores because it keeps no `_id`.

        Returns:
            dict | None: A copy of the document, or None.
        """
        del projection
        document = self.documents.get(query['broker_name'])
        if document is None:
            return None
        return dict(document)

    def replace_one(self, query, document, upsert):
        """Replaces or inserts the document for one broker name.

        Args:
            query (dict): The filter, naming `broker_name`.
            document (dict): The new document.
            upsert (bool): Whether to insert when nothing matches, which the stand-in always does.

        Returns:
            None: This method returns nothing.
        """
        del upsert
        self.documents[query['broker_name']] = dict(document)


class StandInHashRedis:
    """A stand-in Redis client holding hashes in dictionaries.

    Attributes:
        hashes (dict): Each hash by key.
    """

    def __init__(self):
        """Builds the stand-in with no hashes.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}

    def hget(self, key, field):
        """Reads one hash field.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None.
        """
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field, value):
        """Writes one hash field.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            int: 1.
        """
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hsetnx(self, key, field, value):
        """Writes one hash field only when it is empty.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            int: 1 when written, 0 when the field already held a value.
        """
        if self.hget(key, field) is not None:
            return 0
        return self.hset(key, field, value)

    def hdel(self, key, field):
        """Deletes one hash field.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            int: 1 when a field was deleted, otherwise 0.
        """
        if self.hashes.get(key, {}).pop(field, None) is None:
            return 0
        return 1


class ConnectCheckAndDisconnectExample:
    """Connects twice, checks three requests, disconnects and checks again.

    Attributes:
        mongo_db (dict): The stand-in MongoDB database, holding the `last_login` collection.
        cache (StandInHashRedis): The stand-in Redis.
        store (TokenStore): The token store being shown.
    """

    def __init__(self):
        """Stores the January token in the stand-ins and builds the store.

        Returns:
            None: This method returns nothing.
        """
        collection = StandInCollection()
        january = {
            'broker_name': 'unified_broker_interface',
            'access_token': OLD_TOKEN,
            'last_login': '2026-01-05 16:02:11.402913',
            'expires_at': '2026-01-06 16:02:11.402913',
        }
        collection.documents['unified_broker_interface'] = january
        self.mongo_db = {
            'last_login': collection,
        }
        self.cache = StandInHashRedis()
        self.store = TokenStore(self.mongo_db, self.cache)

    def run(self):
        """Walks the token through the day and prints what each step decides.

        Returns:
            None: This method returns nothing.
        """
        document, issued = self.store.connect(3600)
        token = document['access_token']
        print(f'First connect minted a new token: {issued}; replaced the old one: {token != OLD_TOKEN}')
        print(f'  token is a UUID: {str(uuid.UUID(token)) == token}')
        issued_at = datetime.datetime.strptime(document['last_login'], '%Y-%m-%d %H:%M:%S.%f')
        expires_at = datetime.datetime.strptime(document['expires_at'], '%Y-%m-%d %H:%M:%S.%f')
        print(f'  accepted for {(expires_at - issued_at).total_seconds()} seconds')
        cached = json.loads(self.cache.hget('last_login', 'unified_broker_interface'))
        print(f'  Redis copy matches MongoDB: {cached == self.mongo_db["last_login"].documents["unified_broker_interface"]}')
        again, issued_again = self.store.connect(3600)
        print(f'Second connect minted a new token: {issued_again}; same token: {again["access_token"] == token}')
        accepted, error = self.store.check(token)
        print(f'Request with the token: accepted {accepted is not None}, error {error}')
        accepted, error = self.store.check(OLD_TOKEN)
        print(f'Request with the January token: accepted {accepted is not None}, error {error}')
        print(f'Token in force per current(): same token {self.store.current()["access_token"] == token}')
        self.store.revoke()
        print(f'After revoke, token in force: {self.store.current()["access_token"]}')
        accepted, error = self.store.check(token)
        print(f'Request with the revoked token: accepted {accepted is not None}, error {error}')
        fresh = self.store.issue(60)
        print(f'issue() after revoke gives a new token: {fresh["access_token"] != token}')


if __name__ == '__main__':
    ConnectCheckAndDisconnectExample().run()
