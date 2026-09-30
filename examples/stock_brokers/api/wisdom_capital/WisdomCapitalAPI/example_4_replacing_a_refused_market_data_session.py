"""Replaces a refused market data session, reusing one another process already obtained where it can.

Wisdom Capital's platform issues exactly one market data session per application key, and a second login invalidates the first token. So when a process finds its market data token refused, it calls `replace_market_data_session` with that stale token. If another process has already published a different token in the shared login, that token is returned and nobody logs in. Otherwise the process takes a Redis lock, checks once more, and logs in itself, releasing the lock afterwards whatever happens. `market_data_session` reads the market data token and user id in force from the shared login.

The program shows both paths. In the first, another process has already replaced the token, so the call returns it without taking the lock. In the second, nothing has replaced it, so the lock is taken and a login is attempted; the settings here deliberately lack the market data key pair, so the login stops with a `WisdomCapitalAPIException` before sending anything, and the lock is released.

The real constructor reads the settings from MongoDB and logs in to both of Wisdom Capital's applications when their stored tokens no longer work. This program must never log in, so a small subclass, `WisdomCapitalAPIWithoutLogin`, skips that constructor and is handed the settings and a stand-in for Redis that holds the shared login and the lock. No request reaches the network.

Notice that the first path takes no lock, and that the second path leaves no lock behind although the login failed.

Run it from the project root:

    python examples/stock_brokers/api/wisdom_capital/WisdomCapitalAPI/example_4_replacing_a_refused_market_data_session.py
"""

import json
import logging

from stock_brokers.api.wisdom_capital import (
    MARKET_DATA_LOCK_KEY,
    WisdomCapitalAPI,
    WisdomCapitalAPIException,
)

MORNING_LOGIN = {
    'broker_name': 'wisdom_capital',
    'access_token': 'interactive-token',
    'last_login': '2026-09-30 07:00:05',
    'market_data_access_token': 'market-data-token-morning',
    'market_data_user_id': 'WC0001',
}

REPLACED_LOGIN = {
    'broker_name': 'wisdom_capital',
    'access_token': 'interactive-token',
    'last_login': '2026-09-30 07:00:05',
    'market_data_access_token': 'market-data-token-noon',
    'market_data_user_id': 'WC0001',
}


class SharedLoginCache:
    """A dictionary-backed stand-in for Redis, holding the shared login and the market data lock.

    Attributes:
        hashes (dict): Each hash name mapped to a dictionary of its fields.
        keys (dict): Each plain key mapped to its value.
        locks_taken (list): Every key set with `nx=True` that was not already present.
    """

    def __init__(self):
        """Starts with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {}
        self.keys = {}
        self.locks_taken = []

    def hget(self, name, key):
        """Reads one field of a hash.

        Args:
            name (str): The hash name.
            key (str): The field name.

        Returns:
            str | None: The stored value, or None when there is none.
        """
        fields = self.hashes.get(name, {})
        return fields.get(key)

    def hset(self, name, key, value):
        """Writes one field of a hash, as a login does.

        Args:
            name (str): The hash name.
            key (str): The field name.
            value (str): The value to store.

        Returns:
            int: Always 1, the number of fields Redis reports written.
        """
        if name not in self.hashes:
            self.hashes[name] = {}
        self.hashes[name][key] = value
        return 1

    def set(self, name, value, nx=False, ex=None):
        """Sets a plain key, only when it is absent if `nx` is given, as the lock is taken.

        Args:
            name (str): The key.
            value (str): The value to store.
            nx (bool): True to set the key only when it does not exist.
            ex (int | None): The expiry in seconds, which the stand-in ignores.

        Returns:
            bool: True when the key was set.
        """
        if nx and name in self.keys:
            return False
        self.keys[name] = value
        if nx:
            self.locks_taken.append(name)
        return True

    def delete(self, name):
        """Removes a plain key, as the lock is released.

        Args:
            name (str): The key.

        Returns:
            int: 1 when the key existed, otherwise 0.
        """
        if name in self.keys:
            del self.keys[name]
            return 1
        return 0


class WisdomCapitalAPIWithoutLogin(WisdomCapitalAPI):
    """A `WisdomCapitalAPI` that is handed its settings and cache instead of loading them and logging in.

    The real constructor reads the `wisdom_capital` settings document from MongoDB and then establishes both of the platform's sessions. This subclass sets the same attributes from what it is given and does nothing else.
    """

    def __init__(self, cache, settings, stored_login):
        """Sets the attributes the real constructor would have loaded.

        Args:
            cache (SharedLoginCache): The stand-in for Redis, already holding the shared login.
            settings (dict): The broker's settings document.
            stored_login (dict): The broker's `last_login` document, as the real constructor reads it from MongoDB.

        Returns:
            None: This method returns nothing.
        """
        self._broker_name = 'wisdom_capital'
        self._cache = cache
        self._mongo_db = None
        self._logger = logging.getLogger('wisdom_capital')
        self._settings = settings
        self._last_login = stored_login
        self.market_data_session_error = None


class ReplacingAMarketDataSessionExample:
    """Replaces a refused market data token once when another process already has, and once when nobody has.

    Attributes:
        settings (dict): The broker's settings document, without the market data key pair.
    """

    def __init__(self):
        """Holds the settings both paths use.

        Returns:
            None: This method returns nothing.
        """
        self.settings = {
            'ucc_code': 'WC0001',
        }

    def build_api(self, shared_login):
        """Builds an API object whose shared login is the one given.

        Args:
            shared_login (dict): The login document another process last wrote to Redis.

        Returns:
            tuple: (SharedLoginCache, WisdomCapitalAPIWithoutLogin), the stand-in cache and the API object.
        """
        cache = SharedLoginCache()
        cache.hset('last_login', 'wisdom_capital', json.dumps(shared_login))
        api = WisdomCapitalAPIWithoutLogin(cache, self.settings, MORNING_LOGIN)
        return cache, api

    def run(self):
        """Runs both paths and prints what each returned or raised.

        Returns:
            None: This method returns nothing.
        """
        print('Path 1: another process has already replaced the refused token.')
        cache, api = self.build_api(MORNING_LOGIN)
        print(f'    Session in force: {api.market_data_session()}')
        cache.hset('last_login', 'wisdom_capital', json.dumps(REPLACED_LOGIN))
        session = api.replace_market_data_session(stale_access_token='market-data-token-morning')
        print(f'    Replacement returned: {session}')
        print(f'    Locks taken: {cache.locks_taken}')

        print('Path 2: nobody has replaced it, and the settings lack the market data key pair.')
        cache, api = self.build_api(MORNING_LOGIN)
        try:
            api.replace_market_data_session(stale_access_token='market-data-token-morning')
        except WisdomCapitalAPIException as error:
            print(f'    Raised: {type(error).__name__} code={error.code}')
            print(f'    message: {error.message}')
        print(f'    Locks taken: {cache.locks_taken}')
        print(f'    Lock still held: {MARKET_DATA_LOCK_KEY in cache.keys}')


if __name__ == '__main__':
    ReplacingAMarketDataSessionExample().run()
