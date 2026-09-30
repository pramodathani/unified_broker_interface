"""Shows a Fyers rate limit pausing the source, and which Fyers refusals are about the session.

Fyers sits behind Cloudflare, which bans an address that keeps sending after being told to stop, and every further request extends the ban. So when Fyers refuses a quote with its rate limit, `fetch` pauses the source for five minutes before passing the exception on, and while the pause lasts it raises `QuoteUnavailable` without sending anything. The quote service then moves straight on to the next broker. A Cloudflare block page pauses it for thirty minutes in the same way.

`is_authentication_error` never counts a rate limit or a block as a session problem, because logging in only adds requests. It does count Fyers' authentication error codes, such as -16, and it also counts text saying the token has expired.

The API client is a stand-in class that raises the `FyersAPIException` the real client raises for HTTP 429, and counts the requests it receives. Nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/fyers/FyersQuoteSource/example_2_rate_limit_pauses_the_source.py
"""

from stock_brokers.api.fyers import (
    FyersAPIException,
)
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.fyers import (
    FyersQuoteSource,
)


class RateLimitedFyersClient:
    """A stand-in for Fyers' API client whose every request is refused with Fyers' rate limit.

    Attributes:
        request_count (int): How many requests were received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.request_count = 0

    def get(self, url, params=None, timeout=None):
        """Refuses the request the way the real client does for HTTP 429.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters.
            timeout (float): How long the caller would wait.

        Returns:
            dict: Never returns.

        Raises:
            FyersAPIException: Always, carrying the status and Fyers' message.
        """
        self.request_count += 1
        raise FyersAPIException(code=429, message='request limit reached')


class RateLimitPausesTheSourceExample:
    """Sends two quote requests to a rate-limited Fyers, then classifies several refusals.

    Attributes:
        source (FyersQuoteSource): The quote source being shown.
        client (RateLimitedFyersClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = FyersQuoteSource()
        self.client = RateLimitedFyersClient()

    def run(self):
        """Prints what each request raised, how many were sent, and each refusal's classification.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '10100000003045',
            'order_symbol': 'NSE:SBIN-EQ',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000012',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        attempts = [
            'first',
            'second',
        ]
        for attempt in attempts:
            try:
                self.source.fetch(self.client, handle, identity, 1789446605.0)
            except FyersAPIException as error:
                print(f'{attempt} request: FyersAPIException {error.args}')
                print(f'    log in again: {self.source.is_authentication_error(error)}')
            except QuoteUnavailable as error:
                print(f'{attempt} request: QuoteUnavailable: {error}')
        print(f'Requests that reached Fyers: {self.client.request_count}')
        refusals = [
            FyersAPIException(code=-16, message='Could not authenticate the user'),
            FyersAPIException(code=-99, message='Token expired, generate a new access token'),
            FyersAPIException(code=429, message='error code: 1015 You are being rate limited, Cloudflare'),
            FyersAPIException(code=-300, message='Please provide a valid symbol'),
        ]
        for refusal in refusals:
            print(f'{refusal.args} -> log in again: {self.source.is_authentication_error(refusal)}')


if __name__ == '__main__':
    RateLimitPausesTheSourceExample().run()
