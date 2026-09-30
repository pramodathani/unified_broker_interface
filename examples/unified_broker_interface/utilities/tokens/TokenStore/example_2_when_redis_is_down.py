"""Shows how `TokenStore` refuses bad tokens and keeps working when Redis cannot be reached.

MongoDB is the record of the REST API's access token and Redis is the copy read on every request. When Redis cannot be read, `current` reads MongoDB instead, so requests are still checked. When a write to Redis fails, the store deletes the Redis copy instead, so no later read trusts a token that has since been replaced. `check` refuses a missing header, a token that is not the one in force, and a token whose `expires_at` has passed or is missing.

This program uses a stand-in MongoDB collection that holds documents in a dictionary and a stand-in Redis whose reads and writes can be switched to fail, and which records each command. A logging handler prints the store's own warnings to the output without timestamps. The documents it stores by hand carry fixed dates in the past, so the output never depends on the day it runs.

Notice that the first check finds Redis empty, reads MongoDB and fills the Redis copy with HSETNX, so later checks read Redis only; that with Redis failing the token is still found in MongoDB, that the failed write is followed by an HDEL, and that a document written before tokens expired, with no `expires_at`, is refused as expired.

Run it from the project root:

    python examples/unified_broker_interface/utilities/tokens/TokenStore/example_2_when_redis_is_down.py
"""

import logging
import sys

from unified_broker_interface.utilities.tokens import (
    TokenStore,
)

TOKEN = '0f1e2d3c-4b5a-4968-8776-655443322110'


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
            projection (dict): The fields to leave out, which the stand-in ignores.

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


class FlakyRedis:
    """A stand-in Redis client whose reads and writes can be made to fail, recording every command.

    Attributes:
        hashes (dict): Each hash by key.
        failing (bool): Whether reads and writes other than HDEL fail.
        commands (list): The name of every command received.
    """

    def __init__(self):
        """Builds a working stand-in with no hashes.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.failing = False
        self.commands = []

    def refuse_when_failing(self, command):
        """Records a command and fails it when the stand-in is failing.

        Args:
            command (str): The command's name.

        Returns:
            None: This method returns nothing.

        Raises:
            ConnectionError: When the stand-in is failing.
        """
        self.commands.append(command)
        if self.failing:
            raise ConnectionError('Error 111 connecting to 127.0.0.1:6379. Connection refused.')

    def hget(self, key, field):
        """Reads one hash field.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None.
        """
        self.refuse_when_failing('HGET')
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
        self.refuse_when_failing('HSET')
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
        self.refuse_when_failing('HSETNX')
        stored = self.hashes.setdefault(key, {})
        if field in stored:
            return 0
        stored[field] = value
        return 1

    def hdel(self, key, field):
        """Deletes one hash field, which works even while failing, as it would once Redis is back.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            int: 1 when a field was deleted, otherwise 0.
        """
        self.commands.append('HDEL')
        if self.hashes.get(key, {}).pop(field, None) is None:
            return 0
        return 1


class WhenRedisIsDownExample:
    """Checks tokens with Redis working and failing, and with documents of different ages.

    Attributes:
        collection (StandInCollection): The stand-in `last_login` collection.
        cache (FlakyRedis): The stand-in Redis.
        store (TokenStore): The token store being shown.
    """

    def __init__(self):
        """Builds the stand-ins and the store.

        Returns:
            None: This method returns nothing.
        """
        self.collection = StandInCollection()
        mongo_db = {
            'last_login': self.collection,
        }
        self.cache = FlakyRedis()
        self.store = TokenStore(mongo_db, self.cache)

    def put(self, expires_at):
        """Stores a login document for the token directly in MongoDB and clears the Redis copy.

        Args:
            expires_at (str | None): The document's expiry, or None to leave it out as old documents did.

        Returns:
            None: This method returns nothing.
        """
        document = {
            'broker_name': 'unified_broker_interface',
            'access_token': TOKEN,
            'last_login': '2026-09-01 07:05:00.000000',
        }
        if expires_at is not None:
            document['expires_at'] = expires_at
        self.collection.documents['unified_broker_interface'] = document
        self.cache.hashes = {}

    def check(self, label, access_token):
        """Checks one token and prints the decision and the Redis commands it caused.

        Args:
            label (str): What is being checked, for the printout.
            access_token (str | None): The request's token.

        Returns:
            None: This method returns nothing.
        """
        self.cache.commands = []
        accepted, error = self.store.check(access_token)
        print(f'{label}: accepted {accepted is not None}, error {error}, Redis commands {self.cache.commands}')

    def run(self):
        """Checks tokens under each condition, then stores a token while Redis fails.

        Returns:
            None: This method returns nothing.
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('  log %(levelname)s: %(message)s'))
        logging.getLogger('rest_api.tokens').addHandler(handler)
        self.put('2099-01-01 00:00:00.000000')
        self.check('No header', None)
        self.check('Wrong token, Redis empty', '11111111-1111-4111-8111-111111111111')
        self.check('Right token, read from Redis', TOKEN)
        self.check('Right token again', TOKEN)
        self.cache.failing = True
        self.check('Right token, Redis failing', TOKEN)
        self.cache.failing = False
        self.put('2026-09-02 07:05:00.000000')
        self.check('Expired token', TOKEN)
        self.put(None)
        self.check('Token with no expiry', TOKEN)
        self.cache.hashes = {
            'last_login': {
                'unified_broker_interface': '{"access_token": "stale"}',
            },
        }
        self.cache.failing = True
        self.cache.commands = []
        self.store.revoke()
        print(f'Revoke while Redis fails: Redis commands {self.cache.commands}, copy left {self.cache.hashes["last_login"]}')
        print(f'MongoDB now holds token {self.collection.documents["unified_broker_interface"]["access_token"]}')


if __name__ == '__main__':
    WhenRedisIsDownExample().run()
