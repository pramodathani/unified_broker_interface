"""Shows `NorenRefusal` being raised when Noren refuses a dead session inside a successful HTTP response.

Noren answers a refused request with HTTP 200 and a body of `{"stat": "Not_Ok", "emsg": ...}`, so the API client sees a success and hands the body on. `NorenQuoteSource.fetch` inspects the body, and when Noren's message says the session has expired or its session key is invalid it raises `NorenRefusal` carrying that message. `NorenRefusal` is a plain `Exception` subclass with no attributes of its own, and `is_authentication_error` always answers True for it, which is how the quote service knows to log in again.

Flattrade's API client is replaced by a stand-in class that answers `GetQuotes` with the refusal Flattrade sends for a stale session key. Nothing leaves the process.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/noren/NorenRefusal/example_1_session_expired_inside_a_success.py
"""

from unified_broker_interface.utilities.broker_quotes.flattrade import (
    FlattradeQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.utilities.noren import (
    NorenRefusal,
)


class StaleSessionFlattradeClient:
    """A stand-in for Flattrade's API client whose session key Noren no longer accepts."""

    def post(self, url, data=None, timeout=None):
        """Answers with Noren's refusal of the session, inside a successful response.

        Args:
            url (str): The endpoint asked.
            data (dict): The request body.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding Noren's refusal under `data`.
        """
        return {
            'status': 'success',
            'code': 200,
            'data': {
                'stat': 'Not_Ok',
                'emsg': 'Session Expired :  Invalid Session Key',
            },
        }


class SessionExpiredInsideASuccessExample:
    """Fetches one quote with a stale session and prints the refusal raised.

    Attributes:
        source (FlattradeQuoteSource): The quote source that raises the refusal.
        client (StaleSessionFlattradeClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = FlattradeQuoteSource()
        self.client = StaleSessionFlattradeClient()

    def run(self):
        """Prints the caught refusal and whether logging in again would help.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '2885',
            'order_symbol': 'RELIANCE-EQ',
            'lot_size': '1',
            'tick_size': '0.1',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000002',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        try:
            self.source.fetch(self.client, handle, identity, 1789446605.0)
        except NorenRefusal as refusal:
            print(f'Caught: {type(refusal).__name__}')
            print(f'Message: {refusal}')
            print(f'Arguments: {refusal.args}')
            print(f'Log in again: {self.source.is_authentication_error(refusal)}')


if __name__ == '__main__':
    SessionExpiredInsideASuccessExample().run()
