"""Sorts Wisdom Capital's refusals into rate limits, refused sessions and everything else.

Wisdom Capital's platform, Symphony XTS, rate limits every request on a rolling window, and it checks the token before it checks the rate. So a request refused for rate still proves the token is good, while one refused for its token means a fresh login is needed. `WisdomCapitalAPI.is_rate_limited` and `WisdomCapitalAPI.is_session_refused` make that call from whatever a request raised, by its code (429 or 401) or by the XTS error codes in its text (`e-apirl` for rate, `e-session` and `e-token` for the session).

The constructor uses them to decide whether to log in again: it keeps the stored token after a rate limit, logs in after a refused session, and keeps the token when the error says nothing either way, such as a gateway error or a dropped connection, because a new market data login would invalidate the token every other process is using.

Both are static methods and need no logged-in object, so this program builds only exceptions, of the kinds the platform and the network produce. It reaches no broker.

Notice that the gateway error and the dropped connection are neither, which is what keeps a passing outage from triggering a login.

Run it from the project root:

    python examples/stock_brokers/api/wisdom_capital/WisdomCapitalAPI/example_3_telling_rate_limits_from_refused_sessions.py
"""

import requests

from stock_brokers.api.wisdom_capital import (
    WisdomCapitalAPI,
    WisdomCapitalAPIException,
)


class TellingRefusalsApartExample:
    """Classifies a list of errors and says what the constructor would do after each.

    Attributes:
        errors (list): Pairs of (description, exception) to classify.
    """

    def __init__(self):
        """Builds the errors to classify.

        Returns:
            None: This method returns nothing.
        """
        self.errors = [
            (
                'HTTP 429 from the gateway',
                WisdomCapitalAPIException(code=429, message='Too Many Requests'),
            ),
            (
                'XTS rate limit code',
                WisdomCapitalAPIException(code='e-apirl-0004', message='Rate limit exceeded for user WC0001'),
            ),
            (
                'XTS missing or expired token',
                WisdomCapitalAPIException(code='e-token-0002', message='Please Provide token to Authenticate'),
            ),
            (
                'HTTP 401',
                WisdomCapitalAPIException(code=401, message='Unauthorized'),
            ),
            (
                'HTTP 502 gateway page',
                WisdomCapitalAPIException(code=502, message='<html><body><h1>502 Bad Gateway</h1></body></html>'),
            ),
            (
                'dropped connection',
                requests.ConnectionError('Connection aborted.'),
            ),
        ]

    def run(self):
        """Prints each error's classification and the resulting decision.

        Returns:
            None: This method returns nothing.
        """
        for description, error in self.errors:
            rate_limited = WisdomCapitalAPI.is_rate_limited(error)
            session_refused = WisdomCapitalAPI.is_session_refused(error)
            if rate_limited:
                decision = 'keep the token, it authenticated'
            elif session_refused:
                decision = 'log in again'
            else:
                decision = 'keep the token, the error says nothing about it'
            print(f'{description}:')
            print(f'    rate limited={rate_limited} session refused={session_refused} -> {decision}')


if __name__ == '__main__':
    TellingRefusalsApartExample().run()
