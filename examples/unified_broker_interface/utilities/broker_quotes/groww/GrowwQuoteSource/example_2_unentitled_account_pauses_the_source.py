"""Shows Groww refusing live data to an account without the entitlement, the pause that follows, and which Groww refusals are about the session.

An account that is not entitled to Groww's live data gets HTTP 403, "Access forbidden for this request.", on every quote. Asking again cannot help, so `fetch` pauses the source for fifteen minutes before passing the exception on, and while the pause lasts it raises `QuoteUnavailable` without sending anything. A rate limit pauses it for sixty seconds in the same way.

`is_authentication_error` never counts a 403 or a rate limit as a session problem, because logging in again cannot fix either. It does count HTTP 401 and text about an expired token or a JWT.

The API client is a stand-in class that raises the `GrowwAPIException` the real client raises for that 403, and counts the requests it receives. Nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/groww/GrowwQuoteSource/example_2_unentitled_account_pauses_the_source.py
"""

from stock_brokers.api.groww import (
    GrowwAPIException,
)
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.groww import (
    GrowwQuoteSource,
)


class UnentitledGrowwClient:
    """A stand-in for Groww's API client on an account without live data.

    Attributes:
        request_count (int): How many requests were received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.request_count = 0

    def get(self, url, timeout=None, params=None):
        """Refuses the request the way the real client does for Groww's 403.

        Args:
            url (str): The endpoint asked.
            timeout (float): How long the caller would wait.
            params (dict): The query parameters.

        Returns:
            dict: Never returns.

        Raises:
            GrowwAPIException: Always, carrying the status and Groww's message.
        """
        self.request_count += 1
        raise GrowwAPIException(code='403', message='Access forbidden for this request.')


class UnentitledAccountPausesTheSourceExample:
    """Sends two quote requests from an unentitled account, then classifies several refusals.

    Attributes:
        source (GrowwQuoteSource): The quote source being shown.
        client (UnentitledGrowwClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = GrowwQuoteSource()
        self.client = UnentitledGrowwClient()

    def run(self):
        """Prints what each request raised, how many were sent, and each refusal's classification.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '17400',
            'order_symbol': 'NHPC',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000013',
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
            except GrowwAPIException as error:
                print(f'{attempt} request: GrowwAPIException {error.args}')
                print(f'    log in again: {self.source.is_authentication_error(error)}')
            except QuoteUnavailable as error:
                print(f'{attempt} request: QuoteUnavailable: {error}')
        print(f'Requests that reached Groww: {self.client.request_count}')
        refusals = [
            GrowwAPIException(code='401', message='Unauthorized'),
            GrowwAPIException(code='GA005', message='JWT token expired'),
            GrowwAPIException(code='429', message='Too many requests'),
            GrowwAPIException(code='GA001', message='Invalid trading symbol'),
        ]
        for refusal in refusals:
            print(f'{refusal.args} -> log in again: {self.source.is_authentication_error(refusal)}')


if __name__ == '__main__':
    UnentitledAccountPausesTheSourceExample().run()
