"""Shows which Dhan failures the quote service answers by logging in again, and which instruments Dhan cannot quote at all.

Dhan refuses a dead or foreign token with HTTP 401 and a body naming code 808, and an expired one with code 807. Both mean a fresh login is the remedy, and `is_authentication_error` says so. Code 806, "data APIs not subscribed", also arrives as a refusal, but logging in cannot fix a missing subscription, so it is deliberately not an authentication error. The program builds the `DhanAPIException` the API client raises for each body and asks the source about it.

Some instruments have no Dhan quote segment at all. An NSE commodity option is one of them, so `fetch` raises `QuoteUnavailable` before any request is sent. The stand-in client used for that call records requests, which shows that none was made.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/dhan/DhanQuoteSource/example_2_refusals_and_unquotable_segments.py
"""

from stock_brokers.api.dhan import (
    DhanAPIException,
)
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.dhan import (
    DhanQuoteSource,
)


class RecordingDhanClient:
    """A stand-in for Dhan's API client that records every request and answers none of them.

    Attributes:
        requests (list): The body of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def post(self, url, json=None, headers=None, timeout=None):
        """Records a request.

        Args:
            url (str): The endpoint asked.
            json (dict): The request body.
            headers (dict): The request headers.
            timeout (float): How long the caller would wait.

        Returns:
            dict: An empty envelope.
        """
        self.requests.append(json)
        return {
            'data': {},
        }


class RefusalsAndUnquotableSegmentsExample:
    """Classifies three Dhan refusals and asks for an instrument Dhan cannot quote.

    Attributes:
        source (DhanQuoteSource): The quote source being shown.
        client (RecordingDhanClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = DhanQuoteSource()
        self.client = RecordingDhanClient()

    def run(self):
        """Prints each refusal's classification and what an unquotable instrument raises.

        Returns:
            None: This method returns nothing.
        """
        refusals = [
            DhanAPIException(code='Invalid_Authentication', message='{"808": "Authentication Failed - Client ID or Token invalid"}'),
            DhanAPIException(code='Invalid_Authentication', message='{"807": "Access token is expired"}'),
            DhanAPIException(code='Data_API_Error', message='{"806": "Data APIs not subscribed"}'),
        ]
        for refusal in refusals:
            print(f'{refusal.args[1]} -> log in again: {self.source.is_authentication_error(refusal)}')
        handle = {
            'broker_token': '467421',
            'order_symbol': 'CRUDEOIL26SEP5700CE',
            'lot_size': '100',
            'tick_size': '0.05',
        }
        identity = {
            'instrument_id': '44444444-4444-5444-8444-000000000001',
            'exchange': 'nse',
            'segment': 'nse_commodity_options',
            'shape': 'option',
        }
        try:
            self.source.fetch(self.client, handle, identity, 1789446605.0)
        except QuoteUnavailable as error:
            print(f'QuoteUnavailable: {error}')
            print(f'    log in again: {self.source.is_authentication_error(error)}')
        print(f'Requests sent: {self.client.requests}')


if __name__ == '__main__':
    RefusalsAndUnquotableSegmentsExample().run()
