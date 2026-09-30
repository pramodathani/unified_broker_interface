"""Shows `FyersBlockedError` raised for Cloudflare's ban page and for Fyers' own rate limit, and that neither is taken for a dead session.

`FyersAPI` checks its stored token with the profile when it is built, and logs in again only when Fyers says the session is dead: codes -8, -15, -16 or -17, or HTTP 401. Before 2026-09-30 it logged in on any refusal, so Cloudflare's HTTP 429 ban page started a login into the ban, and every restart of every poller sent another, which kept the ban going all day. Any HTTP 429 now raises `FyersBlockedError`, and the pollers wait it out. This program sends nothing: it hands `_request` a stand-in response through a stand-in for `requests.request`, and asks `_is_dead_session` about each refusal.

Notice that both 429 answers raise `FyersBlockedError`, which no login follows, while the expired token's -16 and the 401 are the only dead sessions.

Run it from the project root:

    python examples/stock_brokers/api/fyers/FyersBlockedError/example_1_a_ban_page_is_not_a_bad_token.py
"""

import stock_brokers.api.fyers as fyers_module
from stock_brokers.api.fyers import (
    FyersAPI,
    FyersAPIException,
    FyersBlockedError,
)


class StandInResponse:
    """A response with a status, a content type and a body.

    Attributes:
        status_code (int): The HTTP status.
        headers (dict): The headers, with `Content-Type`.
        content (bytes): The body.
    """

    def __init__(self, status_code, content_type, body):
        """Builds the response.

        Args:
            status_code (int): The HTTP status.
            content_type (str): The content type.
            body (str): The body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.headers = {
            'Content-Type': content_type,
        }
        self.content = body.encode()

    def json(self):
        """The body decoded as JSON.

        Returns:
            object: The body.
        """
        return fyers_module.json_lib.loads(self.content)


class StandInRequests:
    """Stands in for the `requests` module, answering every request with one response.

    Attributes:
        response (StandInResponse): The response to give.
    """

    def __init__(self, response):
        """Builds the stand-in.

        Args:
            response (StandInResponse): The response.

        Returns:
            None: This method returns nothing.
        """
        self.response = response

    def request(self, **options):
        """Answers with the response.

        Args:
            **options: The request's options.

        Returns:
            StandInResponse: The response.
        """
        del options
        return self.response


class OfflineFyersAPI(FyersAPI):
    """A Fyers API object built without any store, holding a stand-in login."""

    def __init__(self):
        """Holds a stand-in login and settings instead of reading MongoDB and Redis.

        Returns:
            None: This method returns nothing.
        """
        self._settings = {
            'app_id': 'STANDIN-100',
        }
        self._last_login = {
            'access_token': 'stand-in-token',
        }

    def _current_login(self):
        """The stand-in login.

        Returns:
            dict: The login.
        """
        return self._last_login


class ABanPageIsNotABadTokenExample:
    """Sends four stand-in refusals through `_request` and classifies them.

    Attributes:
        api (OfflineFyersAPI): The API object.
        answers (list): `(description, StandInResponse)` tuples.
    """

    def __init__(self):
        """Builds the API object and the four answers.

        Returns:
            None: This method returns nothing.
        """
        self.api = OfflineFyersAPI()
        self.answers = [
            ('Cloudflare ban page', StandInResponse(429, 'text/html', '<html>Error 1015: you are being rate limited by Cloudflare</html>')),
            ('Fyers rate limit', StandInResponse(429, 'application/json', '{"s": "error", "code": 429, "message": "request limit reached"}')),
            ('expired token', StandInResponse(401, 'application/json', '{"s": "error", "code": -16, "message": "Could not authenticate the user"}')),
            ('plain HTTP 401', StandInResponse(401, 'text/plain', 'Unauthorized')),
        ]

    def run(self):
        """Prints what each refusal raises and whether it counts as a dead session.

        Returns:
            None: This method returns nothing.
        """
        original_requests = fyers_module.requests
        try:
            for description, response in self.answers:
                fyers_module.requests = StandInRequests(response)
                try:
                    self.api._request('GET', 'https://api-t1.fyers.in/api/v3/profile')
                except FyersBlockedError as error:
                    print(f'{description}: FyersBlockedError, dead session {self.api._is_dead_session(error)}')
                except FyersAPIException as error:
                    print(f'{description}: FyersAPIException {error.args[0]}, dead session {self.api._is_dead_session(error)}')
        finally:
            fyers_module.requests = original_requests


if __name__ == '__main__':
    ABanPageIsNotABadTokenExample().run()
