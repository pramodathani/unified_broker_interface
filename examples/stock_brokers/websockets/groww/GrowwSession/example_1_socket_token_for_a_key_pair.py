"""Reads the Groww access token, exchanges a key pair for a socket token, and logs in again once.

`GrowwSession` holds one `GrowwAPI` and reads the access token afresh every time a socket connects. `socket_token_payload` asks Groww for a short-lived socket JWT and subscription id bound to a key pair's public key, authorized with that access token, and unwraps the answer's `payload`. `log_in_again` logs in only when the token a refused socket used is still the one in force.

Constructing the real `GrowwAPI` logs in to Groww, so the program registers a stand-in module under `stock_brokers.api.groww`, and a stand-in `requests` package answers the socket token request. The key pair is a real `GrowwNkeyPair`, freshly generated, so the program prints only the first letter of its public key.

Notice the bearer token in the request, the unwrapped payload, and that the second request with the stale token makes no login.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwSession/example_1_socket_token_for_a_key_pair.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.groww import (
    GrowwNkeyPair,
    GrowwSession,
)


class LoginRecord:
    """The Groww login state every stand-in API object reads, standing in for the Redis `last_login` hash.

    Attributes:
        access_token (str | None): The token in force now.
        login_count (int): How many logins the stand-in API has made.
    """

    access_token = None
    login_count = 0


class StandInGrowwAPI:
    """A stand-in for `GrowwAPI` whose construction is a pretend login."""

    def __init__(self):
        """Logs in, which here only issues the next numbered token.

        Returns:
            None: This method returns nothing.
        """
        LoginRecord.login_count = LoginRecord.login_count + 1
        LoginRecord.access_token = f'groww-token-{LoginRecord.login_count}'
        print(f'Stand-in login number {LoginRecord.login_count}')
        self._settings = {
            'api_key': 'groww-api-key',
        }

    def _current_login(self):
        """The login in force now, as the real class reads it from Redis.

        Returns:
            dict | None: The access token, or None before any login.
        """
        if LoginRecord.access_token is None:
            return None
        return {
            'access_token': LoginRecord.access_token,
        }


class SocketTokenResponse:
    """A stand-in for the `requests` response of Groww's socket token endpoint.

    Attributes:
        status_code (int): The HTTP status.
        body (dict): The JSON body.
        text (str): The body as text.
    """

    def __init__(self, status_code, body):
        """Keeps the answer.

        Args:
            status_code (int): The HTTP status.
            body (dict): The JSON body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.body = body
        self.text = json.dumps(body)

    def json(self):
        """The JSON body.

        Returns:
            dict: The body.
        """
        return self.body

    def raise_for_status(self):
        """Does nothing, because every scripted answer that reaches it succeeded.

        Returns:
            None: This method returns nothing.
        """


class StandInRequests:
    """A stand-in for the `requests` package that answers socket token requests in turn.

    Attributes:
        statuses (list): The HTTP status of each answer, in order.
    """

    def __init__(self, statuses):
        """Keeps the scripted statuses.

        Args:
            statuses (list): The HTTP status of each answer, in order.

        Returns:
            None: This method returns nothing.
        """
        self.statuses = statuses

    def post(self, url, headers, json, timeout):
        """Answers one socket token request.

        Args:
            url (str): The endpoint.
            headers (dict): The request headers, carrying the access token.
            json (dict): The request body with the public key.
            timeout (int): The request timeout in seconds.

        Returns:
            SocketTokenResponse: The answer.
        """
        status = self.statuses.pop(0)
        print(f"Socket token request with {headers['Authorization']} for a key starting {json['socketKey'][0]}: HTTP {status}")
        if status != 200:
            body = {
                'message': 'Unauthorized',
            }
            return SocketTokenResponse(status, body)
        body = {
            'payload': {
                'token': 'socket-jwt',
                'subscriptionId': 'subscription-77',
            },
        }
        return SocketTokenResponse(status, body)


class SocketTokenForAKeyPairExample:
    """Asks a Groww session for a socket token and logs in again around it.

    Attributes:
        session (GrowwSession): The session being shown.
    """

    def __init__(self):
        """Registers the stand-ins and builds the session.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        api_module = types.ModuleType('stock_brokers.api.groww')
        api_module.GrowwAPI = StandInGrowwAPI
        sys.modules['stock_brokers.api.groww'] = api_module
        sys.modules['requests'] = StandInRequests([
            200,
        ])
        self.session = GrowwSession(logging.getLogger('groww.session'))

    def run(self):
        """Prints the token, the socket token payload, and the token after two login requests.

        Returns:
            None: This method returns nothing.
        """
        failed_token = self.session.access_token()
        print(f'Access token: {failed_token}')
        payload = self.session.socket_token_payload(GrowwNkeyPair())
        print(f'Socket token payload: {payload}')
        self.session.log_in_again(failed_token)
        self.session.log_in_again(failed_token)
        print(f'Access token: {self.session.access_token()}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    SocketTokenForAKeyPairExample().run()
