"""Catches `NorenRefusal`, renews the session, and asks again, which is what the quote service does with it.

When a quote fails, the quote service asks the source whether the failure means the session is dead. For a `NorenRefusal` the answer is always yes, so the service renews the session and sends the same request once more. In the project that renewal is done by the broker's login service, and another process may already have stored a newer session key; here a stand-in API client plays both parts. It refuses the first request with Noren's "Session Expired" body, accepts a new session key when told to log in, and then answers with a quote.

Nothing leaves the process and no real login happens. The instant stamped on the tick is fixed.

In the output, notice that the first request is refused, that the client logs in once, and that the second request with the new session key gets a quote.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/noren/NorenRefusal/example_2_logging_in_and_asking_again.py
"""

from unified_broker_interface.utilities.broker_quotes.shoonya import (
    ShoonyaQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.utilities.noren import (
    NorenRefusal,
)


class RenewableShoonyaClient:
    """A stand-in for Shoonya's API client whose stored session key starts out stale.

    Attributes:
        session_key (str): The session key the next request is sent with.
        requests (list): The session key of every request received.
    """

    def __init__(self):
        """Builds the stand-in with a stale session key.

        Returns:
            None: This method returns nothing.
        """
        self.session_key = 'stale-session-key'
        self.requests = []

    def log_in(self):
        """Stores a fresh session key, as the broker's login service would.

        Returns:
            None: This method returns nothing.
        """
        self.session_key = 'fresh-session-key'

    def post(self, url, data=None, timeout=None):
        """Refuses a request sent with the stale key and answers one sent with the fresh key.

        Args:
            url (str): The endpoint asked.
            data (dict): The request body.
            timeout (float): How long the caller would wait.

        Returns:
            dict: The client's envelope, holding Noren's refusal or quote under `data`.
        """
        self.requests.append(self.session_key)
        if self.session_key == 'stale-session-key':
            return {
                'data': {
                    'stat': 'Not_Ok',
                    'emsg': 'Session Expired :  Invalid Session Key',
                },
            }
        return {
            'data': {
                'stat': 'Ok',
                'lp': '1512.35',
                'c': '1498.80',
            },
        }


class LoggingInAndAskingAgainExample:
    """Asks for a quote, renews the session on a refusal, and asks again.

    Attributes:
        source (ShoonyaQuoteSource): The Noren quote source being used.
        client (RenewableShoonyaClient): The stand-in API client.
    """

    def __init__(self):
        """Builds the source and its stand-in client.

        Returns:
            None: This method returns nothing.
        """
        self.source = ShoonyaQuoteSource()
        self.client = RenewableShoonyaClient()

    def run(self):
        """Prints the refusal, the renewal and the quote obtained on the second try.

        Returns:
            None: This method returns nothing.
        """
        handle = {
            'broker_token': '1594',
            'order_symbol': 'INFY-EQ',
            'lot_size': '1',
            'tick_size': '0.1',
        }
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000001',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        try:
            tick = self.source.fetch(self.client, handle, identity, 1789446605.0)
        except NorenRefusal as refusal:
            print(f'First try refused: {refusal}')
            if not self.source.is_authentication_error(refusal):
                raise
            self.client.log_in()
            print('Logged in again')
            tick = self.source.fetch(self.client, handle, identity, 1789446605.0)
        print(f'Second try: {tick["instrument_token"]} last price {tick["last_price"]}, close {tick["ohlc"]["close"]}')
        print(f'Session keys sent: {self.client.requests}')


if __name__ == '__main__':
    LoggingInAndAskingAgainExample().run()
