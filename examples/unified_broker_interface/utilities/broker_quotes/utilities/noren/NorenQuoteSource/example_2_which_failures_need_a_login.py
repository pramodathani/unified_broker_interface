"""Shows which failures of a Noren quote the quote service answers by logging in again, and one that is refused before any request.

Noren refuses in two ways. A refusal inside a successful HTTP response is turned by `fetch` into `NorenRefusal` when it is about the session, and into `QuoteUnavailable` otherwise. A refusal with an HTTP error status is raised by the broker's API client itself, as a `FlattradeAPIException` or `ShoonyaAPIException` carrying Noren's message. `is_authentication_error` answers True for any `NorenRefusal`, and for any other exception whose text says the session has expired or its session key is invalid.

The program classifies five such exceptions with a Flattrade source. It then asks for an instrument whose handle has no token, which `fetch` refuses with `QuoteUnavailable` before sending anything; the stand-in client records requests, and shows that none was made. The message blames the segment even though `nse_equities` does have a Noren exchange, because `fetch` gives the same message for a missing exchange and a missing token.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/noren/NorenQuoteSource/example_2_which_failures_need_a_login.py
"""

from stock_brokers.api.flattrade import (
    FlattradeAPIException,
)
from stock_brokers.api.shoonya import (
    ShoonyaAPIException,
)
from unified_broker_interface.utilities.broker_quotes.base import (
    QuoteUnavailable,
)
from unified_broker_interface.utilities.broker_quotes.flattrade import (
    FlattradeQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.utilities.noren import (
    NorenRefusal,
)


class RecordingNorenClient:
    """A stand-in for a Noren broker's API client that records every request.

    Attributes:
        requests (list): The body of every request received.
    """

    def __init__(self):
        """Builds the stand-in with no requests received.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def post(self, url, data=None, timeout=None):
        """Records a request and answers with nothing.

        Args:
            url (str): The endpoint asked.
            data (dict): The request body.
            timeout (float): How long the caller would wait.

        Returns:
            dict: An empty envelope.
        """
        self.requests.append(data)
        return {}


class WhichFailuresNeedALoginExample:
    """Classifies five Noren failures and asks for an instrument with no token.

    Attributes:
        source (FlattradeQuoteSource): The Noren quote source being shown.
        client (RecordingNorenClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = FlattradeQuoteSource()
        self.client = RecordingNorenClient()

    def run(self):
        """Prints each failure's classification and what the token-less request raises.

        Returns:
            None: This method returns nothing.
        """
        failures = [
            NorenRefusal('flattrade refused the session: Session Expired :  Invalid Session Key'),
            ShoonyaAPIException(code='Not_Ok', message='Session Expired :  Invalid Session Key'),
            FlattradeAPIException(code='Not_Ok', message='Invalid Input : jData is not valid json object'),
            QuoteUnavailable('flattrade returned no quote for NSE|2885: Error Occurred : 5 "no data"'),
            ConnectionError('Connection aborted.'),
        ]
        for failure in failures:
            print(f'{type(failure).__name__}: {failure}')
            print(f'    log in again: {self.source.is_authentication_error(failure)}')
        handle = {
            'broker_token': '',
            'order_symbol': 'MYSTERY-EQ',
            'lot_size': '1',
            'tick_size': '0.05',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000011',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        try:
            self.source.fetch(self.client, handle, identity, 1789446605.0)
        except QuoteUnavailable as error:
            print(f'QuoteUnavailable: {error}')
        print(f'Requests sent: {self.client.requests}')


if __name__ == '__main__':
    WhichFailuresNeedALoginExample().run()
