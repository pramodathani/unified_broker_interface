"""Shows the INDmoney quotes that are refused before or after asking, and which INDmoney refusals are about the session.

INDstocks answers a BSE code for a stock listed on both exchanges with the NSE listing's quote, and nothing in the answer tells the two apart, so `fetch` refuses every BSE cash instrument with `QuoteUnavailable` before sending anything, rather than serve an NSE price as BSE's. A scrip code INDstocks does not know is refused by the API client with "Invalid scrip codes", which `fetch` also turns into `QuoteUnavailable`, so the quote service simply moves on to the next broker.

A dead token is refused with HTTP 403 and a message saying the access token is incorrect, expired or revoked, and `is_authentication_error` recognises it.

The API client is a stand-in class that raises the `INDMoneyAPIException` the real client raises for an unknown scrip code, and records the requests it receives. Nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/indmoney/IndmoneyQuoteSource/example_2_bse_cash_and_refusals.py
"""

from stock_brokers.api.indmoney import (
    INDMoneyAPIException,
)
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.indmoney import (
    IndmoneyQuoteSource,
)


class UnknownScripIndmoneyClient:
    """A stand-in for INDmoney's API client that refuses every scrip code as unknown.

    Attributes:
        requests (list): The query parameters of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def get(self, url, params=None, timeout=None):
        """Refuses the request the way the real client does for an unknown scrip code.

        Args:
            url (str): The endpoint asked.
            params (dict): The query parameters.
            timeout (float): How long the caller would wait.

        Returns:
            dict: Never returns.

        Raises:
            INDMoneyAPIException: Always, carrying INDstocks' error type and message.
        """
        self.requests.append(params)
        raise INDMoneyAPIException(code='RequestValidationException', message='Invalid scrip codes')


class BseCashAndRefusalsExample:
    """Asks INDmoney for a BSE stock and an unknown NFO token, then classifies two refusals.

    Attributes:
        source (IndmoneyQuoteSource): The quote source being shown.
        client (UnknownScripIndmoneyClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = IndmoneyQuoteSource()
        self.client = UnknownScripIndmoneyClient()

    def run(self):
        """Prints what each request raised, which requests were sent, and each refusal's classification.

        Returns:
            None: This method returns nothing.
        """
        requests = [
            (
                {
                    'broker_token': '500325',
                },
                {
                    'instrument_id': '22222222-2222-5222-8222-000000000010',
                    'exchange': 'bse',
                    'segment': 'bse_equities',
                    'shape': 'security',
                },
            ),
            (
                {
                    'broker_token': '99999999',
                },
                {
                    'instrument_id': '22222222-2222-5222-8222-000000000014',
                    'exchange': 'nse',
                    'segment': 'nse_equity_options',
                    'shape': 'option',
                },
            ),
        ]
        for handle, identity in requests:
            try:
                self.source.fetch(self.client, handle, identity, 1789446605.0)
            except QuoteUnavailable as error:
                print(f'QuoteUnavailable: {error}')
        print(f'Requests sent: {self.client.requests}')
        refusals = [
            INDMoneyAPIException(code=403, message='The provided access_token is either incorrect, expired, or has been revoked. The user needs to re-authenticate.'),
            INDMoneyAPIException(code=500, message='Internal server error'),
        ]
        for refusal in refusals:
            print(f'{refusal.args} -> log in again: {self.source.is_authentication_error(refusal)}')


if __name__ == '__main__':
    BseCashAndRefusalsExample().run()
