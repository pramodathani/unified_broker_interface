"""Builds Kotak request URLs on the API host that Kotak assigned to the session.

Kotak gives every session its own API host, returned as `baseUrl` when the login is validated, and refuses a call sent to any other host even when the token is good. So `KotakAPI.url` builds every URL on the `base_url` of the stored login rather than on a fixed host. Kotak has sent that host with and without a scheme and with and without a trailing slash, so `url` tidies it before use, and an account that has never logged in, or whose last login failed and stored the string "None", gets the fallback host `https://gw-napi.kotaksecurities.com`.

The real constructor reads the stored login from MongoDB and logs in to Kotak with a TOTP and an MPIN when the stored token no longer works. This program must never log in, so a small subclass, `KotakAPIWithoutLogin`, skips that constructor and is handed the stored login directly. `url` sends nothing, so no stand-in for Redis or the network is needed.

Notice that the same two paths, one written with a leading slash and one without, come out on a clean `https://` host in every case, and that the last two logins fall back to the default host.

Run it from the project root:

    python examples/stock_brokers/api/kotak/KotakAPI/example_3_building_urls_on_the_assigned_host.py
"""

import logging

from stock_brokers.api.kotak import (
    KotakAPI,
)


class KotakAPIWithoutLogin(KotakAPI):
    """A `KotakAPI` that is handed its stored login instead of loading it and logging in.

    The real constructor reads the `kotak` settings and login documents from MongoDB and logs in to Kotak when the stored token no longer works. This subclass sets only what `url` reads.
    """

    def __init__(self, stored_login):
        """Sets the attributes the real constructor would have loaded.

        Args:
            stored_login (dict | None): The broker's `last_login` document, or None for an account that has never logged in.

        Returns:
            None: This method returns nothing.
        """
        self._broker_name = 'kotak'
        self._cache = None
        self._mongo_db = None
        self._logger = logging.getLogger('kotak')
        self._settings = {}
        self._last_login = stored_login
        self.login_response = None


class BuildingUrlsExample:
    """Builds the same two URLs for logins that stored their host in different forms.

    Attributes:
        stored_logins (list): Pairs of (description, stored login document or None).
        paths (list): The API paths to build URLs for.
    """

    def __init__(self):
        """Lists the stored logins and the paths.

        Returns:
            None: This method returns nothing.
        """
        self.stored_logins = [
            (
                'host stored in full',
                {
                    'broker_name': 'kotak',
                    'access_token': 'session-token',
                    'sid': 'session-id',
                    'base_url': 'https://e21.kotaksecurities.com',
                },
            ),
            (
                'host without a scheme, with a trailing slash',
                {
                    'broker_name': 'kotak',
                    'access_token': 'session-token',
                    'sid': 'session-id',
                    'base_url': 'e43.kotaksecurities.com/',
                },
            ),
            (
                'host padded with spaces',
                {
                    'broker_name': 'kotak',
                    'access_token': 'session-token',
                    'sid': 'session-id',
                    'base_url': ' https://e22.kotaksecurities.com/ ',
                },
            ),
            (
                'a failed login that stored "None"',
                {
                    'broker_name': 'kotak',
                    'access_token': 'None',
                    'base_url': 'None',
                },
            ),
            (
                'an account that has never logged in',
                None,
            ),
        ]
        self.paths = [
            '/quick/user/limits',
            'portfolio/v1/holdings',
        ]

    def run(self):
        """Prints the URLs each stored login produces.

        Returns:
            None: This method returns nothing.
        """
        for description, stored_login in self.stored_logins:
            api = KotakAPIWithoutLogin(stored_login)
            print(f'{description}:')
            for path in self.paths:
                print(f'    {path} -> {api.url(path)}')


if __name__ == '__main__':
    BuildingUrlsExample().run()
