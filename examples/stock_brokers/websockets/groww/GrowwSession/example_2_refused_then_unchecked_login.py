"""Shows a Groww session's socket token request refused, then a login made without checking and a retried request.

When the socket token endpoint answers HTTP 401 or 403, `GrowwSession.socket_token_payload` raises `GrowwSocketRefused`, because it means the access token is dead. The order update socket answers a refusal with `log_in_again_without_checking`, which logs in whether or not another process already replaced the token, and then asks again.

Constructing the real `GrowwAPI` logs in to Groww, so the program registers a stand-in module under `stock_brokers.api.groww`, and a stand-in `requests` package refuses the first socket token request with HTTP 401 and grants the second.

Notice the refusal message carrying the HTTP status and body, the second login, and that the retried request carries the new token.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwSession/example_2_refused_then_unchecked_login.py
"""

import json
import logging
import sys
import types

from stock_brokers.websockets.groww import (
    GrowwNkeyPair,
    GrowwSession,
    GrowwSocketRefused,
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


class RefusedThenUncheckedLoginExample:
    """Recovers a Groww session from a refused socket token request.

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
            401,
            200,
        ])
        self.session = GrowwSession(logging.getLogger('groww.session'))

    def run(self):
        """Requests a socket token, logs in again when refused, and requests again.

        Returns:
            None: This method returns nothing.
        """
        key_pair = GrowwNkeyPair()
        try:
            self.session.socket_token_payload(key_pair)
        except GrowwSocketRefused as refusal:
            print(f'Refused: {refusal}')
            self.session.log_in_again_without_checking()
        payload = self.session.socket_token_payload(key_pair)
        print(f'Socket token payload: {payload}')
        print(f'Logins made: {LoginRecord.login_count}')


if __name__ == '__main__':
    RefusedThenUncheckedLoginExample().run()
