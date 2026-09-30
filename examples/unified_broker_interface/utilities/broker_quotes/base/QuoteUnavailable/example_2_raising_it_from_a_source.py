"""Raises `QuoteUnavailable` from a quote source of your own, and reads what the caught exception carries.

A broker quote source raises `QuoteUnavailable` whenever the broker has no usable quote. It is a plain `Exception` subclass with no attributes of its own: everything a caller needs is in its message, which the quote service copies into the answer it gives when every broker has failed. This program writes a tiny source for an imaginary broker that only carries NSE stocks, asks it for a BSE stock, and inspects the exception it raises.

The imaginary broker needs no API client, because it refuses before sending anything, so the program passes None for the client and reaches no network or data store.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/base/QuoteUnavailable/example_2_raising_it_from_a_source.py
"""

from unified_broker_interface.utilities.broker_quotes.base import (
    BrokerQuoteSource,
    QuoteUnavailable,
)


class NseOnlyQuoteSource(BrokerQuoteSource):
    """Fetches quotes from an imaginary broker that carries only NSE stocks."""

    BROKER_NAME = 'nse_only'

    def fetch(self, client, handle, identity, received_at):
        """Refuses every instrument that is not an NSE stock.

        Args:
            client (object): The broker's API client, unused here.
            handle (dict): The broker's order handle for the instrument.
            identity (dict): The instrument's identity.
            received_at (float): The instant to stamp on the tick, in epoch seconds.

        Returns:
            dict: Never returns in this program.

        Raises:
            QuoteUnavailable: The instrument is not an NSE stock.
        """
        if identity['segment'] != 'nse_equities':
            raise QuoteUnavailable(f'{self.BROKER_NAME} carries no quotes for {identity["segment"]}')
        raise QuoteUnavailable(f'{self.BROKER_NAME} is imaginary and has no quote for {handle["broker_token"]}')

    def is_authentication_error(self, exception):
        """Says that nothing this imaginary broker raises is about the session.

        Args:
            exception (Exception): What `fetch` raised.

        Returns:
            bool: Always False.
        """
        return False


class RaisingItFromASourceExample:
    """Asks the imaginary source for a BSE stock and prints what the exception carries.

    Attributes:
        source (NseOnlyQuoteSource): The imaginary quote source.
    """

    def __init__(self):
        """Builds the imaginary source.

        Returns:
            None: This method returns nothing.
        """
        self.source = NseOnlyQuoteSource()

    def run(self):
        """Prints the caught exception's type, message and arguments.

        Returns:
            None: This method returns nothing.
        """
        identity = {
            'instrument_id': '22222222-2222-5222-8222-000000000010',
            'exchange': 'bse',
            'segment': 'bse_equities',
            'shape': 'security',
        }
        handle = {
            'broker_token': '500325',
        }
        try:
            self.source.fetch(None, handle, identity, 1789446605.0)
        except QuoteUnavailable as error:
            print(f'Caught: {type(error).__name__}')
            print(f'Message: {error}')
            print(f'Arguments: {error.args}')
            print(f'Is an Exception: {isinstance(error, Exception)}')
            print(f'Log in again: {self.source.is_authentication_error(error)}')


if __name__ == '__main__':
    RaisingItFromASourceExample().run()
